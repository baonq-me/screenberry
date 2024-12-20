import os
import sys

def get_env(env_name):
    if not os.getenv(env_name):
        sys.exit("Missing env $%s" % env_name)
    return os.getenv(env_name)
