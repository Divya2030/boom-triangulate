import os
# Tests must never make live model calls, regardless of a key file being present
# on the developer's machine. Force the offline path for the whole suite.
os.environ["CHIA_NO_MODEL"] = "1"
