"""Fail closed when a configured model does not match CLI-reported usage."""
def _reported_model_matches(requested, reported):
    if not isinstance(requested, str):
        return False
    if not requested:
        return True
    if not isinstance(reported, list) or not reported:
        return False
    req = requested.split('[', 1)[0].strip().lower()
    aliases = {'haiku': 'haiku', 'sonnet': 'sonnet', 'opus': 'opus'}
    if req in aliases:
        family = aliases[req]
        for item in reported:
            if not isinstance(item, str) or not item:
                return False
            clean = item.split('[', 1)[0].strip().lower()
            if not clean.startswith('claude-' + family + '-'):
                return False
        return True
    for item in reported:
        if not isinstance(item, str) or not item:
            return False
        clean = item.split('[', 1)[0].strip().lower()
        if clean.lower() != req:
            return False
    return True
