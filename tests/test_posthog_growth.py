from pydantic import SecretStr
import pytest
import httpx
from fastapi.testclient import TestClient
from app.config import settings
from app.main import app
from app.models import ClientModule, StaffUser
from app.posthog_growth import normalize_rows
from test_growth import growth_client
from sqlalchemy import select


def configured(monkeypatch):
    monkeypatch.setattr(settings, 'posthog_growth_enabled', True)
    monkeypatch.setattr(settings, 'posthog_project_id', 123)
    monkeypatch.setattr(settings, 'posthog_read_key', SecretStr('test-private-read-secret'))
    monkeypatch.setattr(settings, 'posthog_api_host', 'https://us.posthog.com')


def test_unconfigured_no_network_and_role_module_checks(growth_client,monkeypatch):
    client,sessions=growth_client
    monkeypatch.setattr(settings,'posthog_growth_enabled',False)
    monkeypatch.setattr('app.posthog_growth.read_activity',lambda _:pytest.fail('No provider calls while disabled'))
    path='/api/v1/admin/growth/website-activity'
    assert client.get(path).json()['status']=='disabled'
    monkeypatch.setattr(settings,'posthog_growth_enabled',True)
    monkeypatch.setattr(settings,'posthog_read_key',SecretStr(''))
    assert client.get(path).json()['status']=='not_configured'
    with TestClient(app) as unauthenticated:
        assert unauthenticated.get(path).status_code==401
    with sessions() as db:
        db.get(ClientModule,'growth_analytics').enabled=False
        db.commit()
    assert client.get(path).status_code==403
    with sessions() as db:
        db.get(ClientModule,'growth_analytics').enabled=True
        db.scalar(select(StaffUser).where(StaffUser.username=='growth.test')).role='staff'
        db.commit()
    assert client.get(path).status_code==403


def test_aggregate_only_demo_separation_timezone_and_private_response(growth_client,monkeypatch):
    client,_=growth_client
    configured(monkeypatch)
    queries=[]
    def query(sql):
        queries.append(sql)
        return {'results':[['page_viewed',7,4]],'private':'PATIENT SECRET','query':'sensitive source'}
    monkeypatch.setattr('app.posthog_growth.read_activity',query)
    path='/api/v1/admin/growth/website-activity?start_date=2026-01-02&end_date=2026-01-02'
    result=client.get(path)
    assert result.status_code==200
    body=result.json()
    assert body['status']=='available'
    assert body['rows'][0]['events']==7 and body['rows'][0]['visitors']==4
    assert body['visitor_to_appointment_conversion'] is None
    assert body['scope']=='whole_website'
    assert 'PRIVATE' not in result.text.upper() and 'read-secret' not in result.text
    assert "properties.is_demo = false" in queries[0]
    assert "properties.environment = 'production'" in queries[0]
    assert "2026-01-01 18:30:00" in queries[0] and "2026-01-02 18:30:00" in queries[0]
    assert 'GROUP BY event' in queries[0] and 'SELECT *' not in queries[0]
    assert client.get(path+'&traffic=demo').json()['traffic']=='demo'
    assert 'properties.is_demo = true' in queries[1]
    assert "properties.environment = 'production'" not in queries[1]


def test_vendor_failure_invalid_host_schema_and_dates(growth_client,monkeypatch):
    client,_=growth_client
    configured(monkeypatch)
    path='/api/v1/admin/growth/website-activity'
    monkeypatch.setattr(settings,'posthog_api_host','https://us.i.posthog.com')
    assert client.get(path).json()['status']=='invalid_host'
    monkeypatch.setattr(settings,'posthog_api_host','https://us.posthog.com')
    def failure(_):raise httpx.TimeoutException('private key must never be returned')
    monkeypatch.setattr('app.posthog_growth.read_activity',failure)
    result=client.get(path)
    assert result.json()['status']=='unavailable' and 'private key' not in result.text
    for params in ['?traffic=any','?start_date=2026-01-02&end_date=2026-01-01','?start_date=2026-01-01&end_date=2026-06-01','?reporting_timezone=bad']:
        assert client.get(path+params).status_code==422
    for data in [{'results':[['unexpected',1,1]]},{'results':[['page_viewed',1,2]]},{'results':[['page_viewed',True,1]]},{'results':[['page_viewed',-1,0]]},{'results':[['page_viewed',1,1],['page_viewed',2,2]]}]:
        with pytest.raises(ValueError):normalize_rows(data)
    assert all(row['events']==0 for row in normalize_rows({'results':[]}))
