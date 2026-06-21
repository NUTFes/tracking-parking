def calc_s(y: float, y_min: float, y_max: float) -> float:
    """
    s = (y_max - y) / (y_max - y_min)
    y=y_max（ROI下端=道路側） → s=0.0
    y=y_min（ROI上端=駐車場側） → s=1.0
    """
    if y_max == y_min:
        return 0.0
    return (y_max - y) / (y_max - y_min)
