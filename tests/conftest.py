import os

os.environ["BACKBONE_NO_SECRETS_FILE"] = "1"  # hermetic: no test may read the router's local secrets file or send a real message
