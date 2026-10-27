from types import SimpleNamespace

from app.academic_cohort.personalization import personalized_fuel


def test_missing_manual_price_does_not_claim_an_anp_lookup_or_missing_provider_data():
    value,message=personalized_fuel(None,SimpleNamespace(manual_fuel_price_brl=None))
    assert value is None
    assert 'não consulta preços ANP' in message and 'não é usado como preço manual' in message
    assert 'Não há preço ANP publicado' not in message
