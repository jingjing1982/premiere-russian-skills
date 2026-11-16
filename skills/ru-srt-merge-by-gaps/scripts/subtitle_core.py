def stamp(ms, separator=","):
    if ms < 0: raise ValueError("Negative subtitle time")
    return f"{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02}{separator}{ms%1000:03}"
