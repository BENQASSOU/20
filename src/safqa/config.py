"""Publisher settings.  Edit before building your release APK."""

# Where subscribers send payment / request a licence key (shown in Compte).
SALES_WHATSAPP = "+212600000000"
SALES_EMAIL = "contact@example.ma"
PAYMENT_INFO = ("Paiement par virement bancaire ou versement. Envoyez le reçu par WhatsApp "
                "avec le nom de votre société : votre clé d'activation vous est envoyée sous 24 h.")

# Optional relay server (tools/proxy_server.py).  When set, subscribers use
# AI features with their licence key only - no Anthropic API key needed.
DEFAULT_PROXY_URL = ""

# Safqa Cloud server (accounts, team sync, AI included in the subscription).
# The release build writes safqa/_cloud.py from the SAFQA_CLOUD_URL repository
# secret; users can also type the address in Plus > Compte & équipe.
CLOUD_URL = ""
try:
    from . import _cloud
    CLOUD_URL = _cloud.CLOUD_URL
except ImportError:
    pass
