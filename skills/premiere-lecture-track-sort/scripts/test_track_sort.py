"""Offline regression tests. Uses mocks/synthetic rows; never imports a PR client."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import track_sort as ts
import prepare_preview as pp


ROWS = [[0, 0, 0, 100, 200, 300, 'media.mp4'], [1, 0, 0, 100, 200, 300, 'media.mp4']]
CUTS = [{'frame': 40, 'video_track': 0, 'audio_track': 0}]
MOVES = [{'start': 0, 'end': 40, 'video_track': 0, 'audio_track': 0, 'target_track': 2}]


class PlanTests(unittest.TestCase):
    def test_cut_and_move_preserve_source_offset_and_audio(self):
        steps = ts.model(ROWS, CUTS, MOVES)
        self.assertEqual(steps[-1]['after'], [[0, 0, 40, 100, 240, 300, 'media.mp4'],
                         [0, 2, 0, 40, 200, 240, 'media.mp4'],
                         [1, 0, 0, 40, 200, 240, 'media.mp4'], [1, 0, 40, 100, 240, 300, 'media.mp4']])
        self.assertEqual(ROWS[0][3], 100)  # Input snapshot is immutable.

    def test_recut_rejected(self):
        with self.assertRaises(ValueError):
            ts.model(ROWS, CUTS+CUTS, [])

    def test_wrong_audio_source_rejected(self):
        bad = [r.copy() for r in ROWS]; bad[1][6] = 'different.mp4'
        with self.assertRaises(ValueError):
            ts.model(bad, CUTS, [])

    def test_overlap_rejected(self):
        with self.assertRaises(ValueError):
            ts.model(ROWS+[[0, 2, 0, 100, 200, 300, 'other.mp4']], [], [])

    def test_unsupported_speed_rejected(self):
        bad = [r.copy() for r in ROWS]; bad[0][5] = 400
        with self.assertRaises(ValueError):
            ts.model(bad, [], [])

    def test_prefix_recovery_rejects_partial_cut(self):
        ops = ts.model(ROWS, CUTS, MOVES)
        states = [ROWS]+[s['after'] for s in ops]
        self.assertEqual(ts.position(states, ops[0]['after']), 1)
        partial = [r for r in ops[0]['after'] if r[0] == 0] + [ROWS[1]]
        with self.assertRaises(ValueError):
            ts.position(states, partial)

    def test_frame_timecode(self):
        self.assertEqual(ts.tc(71088, 50), '00:23:41:38')


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.review_mock=patch.object(ts,'validate_review',return_value={'mocked':True})
        self.review_mock.start()
        self.addCleanup(self.review_mock.stop)
        self.prepare_review_mock=patch.object(pp,'validate_review',return_value={'mocked':True})
        self.prepare_review_mock.start()
        self.addCleanup(self.prepare_review_mock.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.ops = ts.model(ROWS, CUTS, MOVES)
        self.cfg = {'preview': 'C:\\preview.prproj', 'main_project': 'C:\\main.prproj',
                    'source_snapshot': 'C:\\frozen.prproj', 'uid': 'test-sequence', 'fps': 50, 'tpf': 5080320000}
        scripts = {'shape.jsx': 'shape-only', 'save.jsx': 'save-only'}
        for i, op in enumerate(self.ops):
            op['script'] = f'{i}.jsx'
            scripts[op['script']] = ts.operation_script(self.cfg, op)
        for n, s in scripts.items():
            (self.folder/n).write_text(s, 'utf-8')
        (self.folder/'baseline.prproj').write_bytes(b'fake baseline for mocked audit')
        (self.folder/'review.json').write_text('{}',encoding='utf-8')
        ts.write(self.folder/'plan.json', {'config': self.cfg, 'baseline': ROWS, 'ops': self.ops,
                 'review_sha256':ts.digest(self.folder/'review.json'),
                 'baseline_sha256': ts.digest(self.folder/'baseline.prproj'),
                 'scripts_sha256': {n: ts.digest(self.folder/n) for n in scripts}})
        self.requests = scripts
        self.adapter = self.folder/'fake_adapter.py'
        self.adapter.write_text('from offline_test_server import run_pr_script\n', 'utf-8')
        self.state = [r.copy() for r in ROWS]
        self.mutations = []
        self.full_reads = 0
        self.crash_after = None
        sys.modules['offline_test_server'] = self

    def tearDown(self):
        del sys.modules['offline_test_server']
        self.temp.cleanup()

    def run_pr_script(self, script):
        if script == 'shape-only':
            self.full_reads += 1
            return {'rows': self.state, 'counts': ts.counts(self.state)}
        if script == 'save-only':
            return {'saved': True}
        index = next(i for i, op in enumerate(self.ops) if self.requests[op['script']] == script)
        op = self.ops[index]
        if self.state != sorted(op['before']):
            raise RuntimeError('Mock native precondition failed')
        self.state = [r.copy() for r in op['after']]
        self.mutations.append(index)
        if index == self.crash_after:
            self.crash_after = None
            raise TimeoutError('Reply lost after native mutation')
        return {'rows': ts.window(self.state, max(0, op['video'][2]-1), op['video'][3]+1),
                'counts': ts.counts(self.state)}

    def test_lost_reply_recovers_without_duplicate_cut(self):
        self.crash_after = 0
        with patch.object(ts, 'audit', return_value={'mocked': True}) as audit:
            with self.assertRaises(TimeoutError):
                ts.run(self.folder, self.adapter, 20)
            ts.run(self.folder, self.adapter, 20)
            self.assertEqual(self.mutations, [0, 1])
            self.assertEqual(ts.read(self.folder/'progress.json')['saved_audited'], 2)
            self.assertGreaterEqual(audit.call_count, 2)

    def test_local_checks_and_phase_global_reads(self):
        with patch.object(ts, 'audit', return_value={'mocked': True}):
            ts.run(self.folder, self.adapter, 20)
        self.assertEqual(self.mutations, [0, 1])
        self.assertEqual(self.full_reads, 3)  # Start, first-cut audit, phase end.

    def test_diverged_timeline_stops_before_write(self):
        self.state[0][2] = 1
        with self.assertRaises(ValueError):
            ts.run(self.folder, self.adapter, 20)
        self.assertEqual(self.mutations, [])

    def test_saved_audit_failure_prevents_following_move(self):
        with patch.object(ts, 'audit', side_effect=[{'mocked':True},ValueError('Broken link')]):
            with self.assertRaises(ValueError):
                ts.run(self.folder, self.adapter, 20)
        self.assertEqual(self.mutations, [0])

    def test_continuous_batches_reuse_previous_full_audit(self):
        with patch.object(ts, 'audit', return_value={'mocked': True}) as audit:
            ts.run(self.folder, self.adapter, 1, until_complete=True)
        self.assertEqual(self.mutations, [0, 1])
        self.assertEqual(self.full_reads, 3)  # Startup and two batch ends, no repeated startup.
        self.assertEqual(audit.call_count, 3)
        self.assertEqual(ts.read(self.folder/'progress.json')['saved_audited'], 2)
        timing = ts.read(next(self.folder.glob('timing-*.json')))
        self.assertEqual(timing['outcome'], 'completed')
        self.assertEqual(timing['calls']['mutation_and_local_check'], 2)

    def test_new_process_still_performs_recovery_audit(self):
        with patch.object(ts, 'audit', return_value={'mocked': True}) as audit:
            ts.run(self.folder, self.adapter, 1)
            ts.run(self.folder, self.adapter, 1, until_complete=True)
        self.assertEqual(self.mutations, [0, 1])
        self.assertEqual(self.full_reads, 4)
        self.assertEqual(audit.call_count, 4)

    def test_continuous_batch_audit_failure_stops_next_batch(self):
        with patch.object(ts, 'audit', side_effect=[{'mocked':True},ValueError('Broken link')]):
            with self.assertRaises(ValueError):
                ts.run(self.folder, self.adapter, 1, until_complete=True)
        self.assertEqual(self.mutations, [0])
        self.assertEqual(ts.read(next(self.folder.glob('timing-*.json')))['outcome'], 'failed')

    def test_continuous_lost_reply_second_batch_recovers_once(self):
        self.crash_after = 1
        with patch.object(ts, 'audit', return_value={'mocked': True}):
            with self.assertRaises(TimeoutError):
                ts.run(self.folder, self.adapter, 1, until_complete=True)
            ts.run(self.folder, self.adapter, 1, until_complete=True)
        self.assertEqual(self.mutations, [0, 1])
        self.assertEqual(ts.read(self.folder/'progress.json')['saved_audited'], 2)

    def test_tampered_operation_rejected_before_connection(self):
        (self.folder/self.ops[0]['script']).write_text('tampered', 'utf-8')
        with self.assertRaises(ValueError):
            ts.run(self.folder, self.adapter, 1, until_complete=True)
        self.assertEqual(self.full_reads, 0)
        self.assertEqual(self.mutations, [])

    def test_move_only_plan_pilots_without_adding_cuts(self):
        initial = sorted(ROWS + [[0, 0, 100, 200, 300, 400, 'media.mp4'],
                                [1, 0, 100, 200, 300, 400, 'media.mp4']])
        moves = [{'start': start, 'end': start+100, 'video_track': 0,
                  'audio_track': 0, 'target_track': 1} for start in (0, 100)]
        self.ops = ts.model(initial, [], moves)
        plan = ts.read(self.folder/'plan.json')
        plan['baseline'], plan['ops'] = initial, self.ops
        for i, op in enumerate(self.ops):
            op['script'] = f'{i}.jsx'
            script = ts.operation_script(self.cfg, op)
            (self.folder/op['script']).write_text(script, 'utf-8')
            self.requests[op['script']] = script
            plan['scripts_sha256'][op['script']] = ts.digest(self.folder/op['script'])
        ts.write(self.folder/'plan.json', plan)
        self.state = initial
        with patch.object(ts, 'audit', return_value={'mocked': True}) as audit:
            ts.run(self.folder, self.adapter, 20, until_complete=True)
        self.assertEqual([op['type'] for op in self.ops], ['move', 'move'])
        self.assertEqual([r for r in self.state if r[0] == 1], [r for r in initial if r[0] == 1])
        self.assertEqual(len(self.state), len(initial))
        self.assertEqual(audit.call_count, 3)  # Initial saved state, first move, batch end.
        self.assertEqual(self.full_reads, 3)

    def test_prepare_is_offline_and_rejects_changed_input(self):
        result = pp.prepare([self.folder], self.folder/'prepared')
        self.assertEqual(len(result['requests']), 4)
        self.assertFalse(result['premiere_contacted'])
        self.assertEqual(self.full_reads, 0)
        (self.folder/'baseline.prproj').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            pp.prepare([self.folder], self.folder/'should-not-exist')
        self.assertFalse((self.folder/'should-not-exist').exists())

    def test_prepared_guards_in_mock_javascript_runtime(self):
        result = pp.prepare([self.folder], self.folder/'prepared')
        scripts = {r['action']: Path(r['file']).read_text('utf-8') for r in result['requests']}
        harness = r'''
const vm=require('vm'), assert=require('assert');
const data=JSON.parse(require('fs').readFileSync(0,'utf8'));
function env(path){
 let writes=[];
 let s={sequenceID:'test-sequence',timebase:'5080320000',videoTracks:{numTracks:0},audioTracks:{numTracks:0}};
 let app={project:{path,activeSequence:s,sequences:{0:s,numSequences:1},
   openSequence(uid){writes.push(['activate',uid]);},save(){throw Error('Must not save');}},
   openDocument(p){writes.push(['open',p]);app.project.path=p;}};
 let ctx=vm.createContext({app});vm.runInContext('Array.prototype.indexOf=undefined',ctx);
 return {ctx,app,writes,s};
}
for(const [kind,script] of Object.entries(data.scripts)){
 let e=env('C:\\unrelated.prproj');
 assert.throws(()=>vm.runInContext(script,e.ctx));assert.equal(e.writes.length,0);
}
let e=env(data.cfg.main_project);
vm.runInContext(data.scripts.source_read,e.ctx);assert.equal(e.writes.length,0);
vm.runInContext(data.scripts.open_existing_preview,e.ctx);
assert.equal(e.app.project.path,data.cfg.preview);assert.equal(e.writes.length,1);
vm.runInContext(data.scripts.activate_preview_sequence,e.ctx);
vm.runInContext(data.scripts.preview_read,e.ctx);
assert.equal(e.writes.length,2);
e.s.sequenceID='wrong';assert.throws(()=>vm.runInContext(data.scripts.preview_read,e.ctx));
let bad=env(data.cfg.main_project);bad.s.timebase='wrong';
assert.throws(()=>vm.runInContext(data.scripts.source_read,bad.ctx));
process.stdout.write('guards passed');
'''
        done = subprocess.run(['node', '-e', harness], input=json.dumps({'scripts': scripts, 'cfg': self.cfg}),
                              text=True, capture_output=True, timeout=20)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('guards passed', done.stdout)


if __name__ == '__main__':
    unittest.main()
