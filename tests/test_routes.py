def test_routes_importa_correctamente():
    from app.api import routes

    assert routes.router is not None