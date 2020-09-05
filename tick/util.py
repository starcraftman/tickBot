"""
Utility functions
-----------------
    BOT - Global reference to the main bot.
    get_config - Pull out configuration information.
    rel_to_abs - Convert relative paths to rooted at project ones.
    init_logging - Project wide logging initialization.
"""
import logging
import logging.handlers
import logging.config
import os
import re

import yaml
try:
    from yaml import CLoader as Loader, CDumper as Dumper
except ImportError:
    from yaml import Loader, Dumper

import tick.exc

BOT = None
MSG_LIMIT = 1950  # Number chars before message truncation
PASTE_LOGIN = "https://pastebin.com/api/api_login.php"
PASTE_UPLOAD = "https://pastebin.com/api/api_post.php"
LOG_MSG = """See main.log for general traces.
Rolling over existing file logs as listed below.
    module_name -> output_file
    =========================="""


def substr_match(seq, line, *, skip_spaces=True, ignore_case=True):
    """
    True iff the substr is present in string. Ignore spaces and optionally case.
    """
    return substr_ind(seq, line, skip_spaces=skip_spaces,
                      ignore_case=ignore_case) != []


def substr_ind(seq, line, *, skip_spaces=True, ignore_case=True):
    """
    Return the start and end + 1 index of a substring match of seq to line.

    Returns:
        [start, end + 1] if needle found in line
        [] if needle not found in line
    """
    if ignore_case:
        seq = seq.lower()
        line = line.lower()

    if skip_spaces:
        seq = seq.replace(' ', '')

    start = None
    count = 0
    for ind, char in enumerate(line):
        if skip_spaces and char == ' ':
            continue

        if char == seq[count]:
            if count == 0:
                start = ind
            count += 1
        else:
            count = 0
            start = None

        if count == len(seq):
            return [start, ind + 1]

    return []


def rel_to_abs(*path_parts):
    """
    Convert an internally relative path to an absolute one.
    """
    return os.path.join(ROOT_DIR, *path_parts)


def get_config(*keys, default=None):
    """
    Return keys straight from yaml config.

    Args:
        keys: The keys going down the config.
        default: A default value to return. If not set, will raise KeyError.

    Raises:
        KeyError: If no default set and keys were not in config.
    """
    try:
        with open(YAML_FILE) as fin:
            conf = yaml.load(fin, Loader=Loader)
    except FileNotFoundError:
        raise tick.exc.MissingConfigFile("Missing config.yml. Expected at: " + YAML_FILE)

    try:
        for key in keys:
            conf = conf[key]

        return conf
    except KeyError:
        if default:
            return default

        raise


def update_config(new_val, *keys):
    """
    Get current config and replace the value of keys with new_val.
    Then flush new config to the file.

    N. B. The key must exist, else KeyError
    """
    try:
        with open(YAML_FILE) as fin:
            conf = yaml.load(fin, Loader=Loader)
    except FileNotFoundError:
        raise tick.exc.MissingConfigFile("Missing config.yml. Expected at: " + YAML_FILE)

    whole_conf = conf
    for key in keys[:-1]:
        conf = conf[key]
    conf[keys[-1]] = new_val

    with open(YAML_FILE, 'w') as fout:
        yaml.dump(whole_conf, fout, Dumper=Dumper, default_flow_style=False)


def init_logging():  # pragma: no cover
    """
    Initialize project wide logging. See config file for details and reference on module.

     - On every start the file logs are rolled over.
     - This must be the first invocation on startup to set up logging.
    """
    log_file = rel_to_abs(get_config('paths', 'log_conf'))
    try:
        with open(log_file) as fin:
            lconf = yaml.load(fin, Loader=Loader)
    except FileNotFoundError:
        raise tick.exc.MissingConfigFile("Missing log.yml. Expected at: " + log_file)

    for handler in lconf['handlers']:
        try:
            os.makedirs(os.path.dirname(lconf['handlers'][handler]['filename']))
        except (OSError, KeyError):
            pass

    with open(log_file) as fin:
        logging.config.dictConfig(yaml.load(fin, Loader=Loader))

    print(LOG_MSG)
    for name in lconf['handlers']:
        node = lconf['handlers'][name]
        if 'RotatingFileHandler' not in node['class']:
            continue

        for handler in logging.getLogger(name).handlers:
            if isinstance(handler, logging.handlers.RotatingFileHandler):
                print('    %s -> %s' % (name, handler.baseFilename))
                handler.doRollover()


def clean_input(text, *, replace='-'):
    """
    Ensure input contains ONLY ASCII characters.
    Any other character will be replaced with 'replace'.

    Args:
        text: The text to clean.
        replace: The replacement character to use.

    Returns:
        The cleaned text.
    """
    text = re.sub(r'[^a-zA-Z0-9-]', replace, text)
    text = re.sub(r'--+', replace, text)

    return text


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YAML_FILE = rel_to_abs('data', 'config.yml')
