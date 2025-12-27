from .models import MarketplaceSetting

def marketplace_settings(request):
    """
    Injects global marketplace settings like Currency into every template.
    """
    try:
        config = MarketplaceSetting.current()
        return {
            'currency_symbol': config.currency_symbol,
            'currency_code': config.currency_code,
            'marketplace_setting': config, # Full object just in case
        }
    except Exception:
        # Fallback if migration hasn't run or DB issue
        return {
            'currency_symbol': '₦',
            'currency_code': 'NGN'
        }
