from waitforit.middleware import WaitForIt

def make_filter(
    app,
    global_conf,
    time_limit='10',
    poll_time='10'):
    time_limit = float(time_limit)
    poll_time = float(poll_time)
    return WaitForIt(app, time_limit=time_limit,
                     poll_time=poll_time)
