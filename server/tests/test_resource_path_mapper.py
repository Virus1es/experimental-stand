from app.services.resource_path_mapper import ResourcePathMapper


def test_different_paths_get_different_ids():
    mapper = ResourcePathMapper([
        "/api/products/3",
        "/api/categories/3",
    ])

    product_path = mapper.http_path("/api/products/3")
    category_path = mapper.http_path("/api/categories/3")

    assert product_path != category_path

    assert mapper.original_path(product_path) == "/api/products/3"
    assert mapper.original_path(category_path) == "/api/categories/3"


def test_new_path_can_be_registered():
    mapper = ResourcePathMapper([
        "/api/products/1",
    ])

    resource_id = mapper.register("/api/products/42")

    assert mapper.id_for("/api/products/42") == resource_id

    assert mapper.original_path(
        f"/api/resources/{resource_id}"
    ) == "/api/products/42"


def test_mapping_is_independent_of_training_path_order():
    first = ResourcePathMapper([
        "/api/products/3",
        "/api/products/1",
    ])

    second = ResourcePathMapper([
        "/api/products/1",
        "/api/products/3",
    ])

    assert first.id_for("/api/products/3") == second.id_for(
        "/api/products/3"
    )
