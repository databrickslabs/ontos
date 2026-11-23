"""PUT /api/settings answers with the warnings of the installed job sync (split from #1486)."""


def test_the_settings_save_returns_the_job_warnings(client, monkeypatch):
    from src.controller.settings_manager import SettingsManager

    warning = {'code': 'compliance_job_not_updated', 'params': {}, 'message': 'm'}
    monkeypatch.setattr(SettingsManager, '_refresh_llm_job_parameters', lambda self: warning)
    calls = []
    real = SettingsManager.update_settings_with_warnings
    monkeypatch.setattr(
        SettingsManager, 'update_settings_with_warnings',
        lambda self, payload: calls.append(payload) or real(self, payload),
    )

    response = client.put('/api/settings', json={'llm_endpoint': 'new-endpoint'})

    assert response.status_code == 200, response.text
    assert response.json()['warnings'] == [warning]
    assert len(calls) == 1
