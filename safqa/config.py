"""Publisher settings.  Edit before building your release APK."""

# Where subscribers send payment / request a licence key (shown in Compte).
SALES_WHATSAPP = "+212600000000"
SALES_EMAIL = "contact@example.ma"
PAYMENT_INFO = ("Paiement par virement bancaire ou versement. Envoyez le reçu par WhatsApp "
                "avec le nom de votre société : votre clé d'activation vous est envoyée sous 24 h.")

# Optional relay server (tools/proxy_server.py).  When set, subscribers use
# AI features with their licence key only - no Anthropic API key needed.
DEFAULT_PROXY_URL = ""
