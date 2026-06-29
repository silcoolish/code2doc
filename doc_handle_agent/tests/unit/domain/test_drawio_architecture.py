from app.domain.drawio_architecture import render_drawio_architecture


def test_drawio_architecture_falls_back_to_layer_edges_when_connections_are_invalid():
    artifacts = render_drawio_architecture(
        {
            "title": "系统架构图",
            "layers": [
                {
                    "id": "frontend",
                    "label": "L1",
                    "name": "前端",
                    "items": [{"id": "desktop", "name": "桌面端"}],
                },
                {
                    "id": "backend",
                    "label": "L2",
                    "name": "后端",
                    "items": [{"id": "workspace", "name": "工作空间服务"}],
                },
            ],
            "connections": [{"from": "missing-source", "to": "missing-target"}],
        },
        include_svg=True,
    )

    assert 'edge="1"' in artifacts.drawio_xml
    assert "marker-end" in artifacts.svg
