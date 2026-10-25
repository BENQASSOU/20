#!/usr/bin/env python3
"""Generate a subscriber licence key.

    export SAFQA_LICENSE_SECRET='same secret as the GitHub repository secret'
    python tools/make_license.py PRO 2027-01-31 "BTP Atlas SARL"

Plans: ESSENTIEL (199 DH), PRO (449 DH), ENTREPRISE (799 DH).
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from safqa import billing  # noqa: E402


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    plan, expiry, customer = sys.argv[1:]
    if not os.environ.get("SAFQA_LICENSE_SECRET"):
        print("Attention : SAFQA_LICENSE_SECRET non défini, clé de développement uniquement.", file=sys.stderr)
    exp = datetime.strptime(expiry, "%Y-%m-%d").date()
    key = billing.make_key(plan, exp, customer)
    print(key)
    ok, _, _, msg = billing.check_key(key)
    print(msg, file=sys.stderr)


if __name__ == "__main__":
    main()
