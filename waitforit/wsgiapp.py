from waitforit.middleware import WaitForIt

def make_filter(
    app,
    global_conf,
    time_limit='10',
    poll_time='10',
    template=None,
    template_filename=None,
    **kw):
    """
    Wrap the application in the WaitForIt middleware.  If the
    application takes more than `time_limit` seconds to respond, a
    wait page will be returned.  The wait page will poll ever
    `poll_time` seconds to see if the application has returned.

    You can give `template_filename`; look in
    ``waitforit/response.tmpl`` for an example.  Or, more simply,
    you can pass in options like `option name=value`; specifically:

      ``option css``:
          The CSS to use
          
      ``option extra_css``:
          Extra CSS to use, in addition to the normal CSS

      ``option css_link``:
          A link to a stylesheet to include
      
      ``option message``:
          HTML to display in the wait page, instead of the default message.
    """
    time_limit = float(time_limit)
    poll_time = float(poll_time)
    template_options = {}
    for name, value in kw.items():
        parts = name.split(None, 1)
        if len(parts) > 1 and parts[0] == 'option':
            template_options[parts[1]] = value
            del kw[name]
    if kw:
        raise ValueError(
            "Unexpected options: %s" % ', '.join(kw.keys()))
    return WaitForIt(app, time_limit=time_limit,
                     poll_time=poll_time,
                     template=template or None,
                     template_filename=template_filename or None,
                     template_options=template_options,
                     )
