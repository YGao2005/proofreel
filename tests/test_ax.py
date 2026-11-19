from proofreel.ax import flatten, matches

SCREEN = (0, 0, 1470, 956)


def window(*children):
    return {"role": "AXWindow", "title": "Untitled", "frame": [100, 50, 600, 400], "children": list(children)}


def test_points_become_pixels_at_the_screen_scale():
    button = {"role": "AXButton", "title": "Save", "frame": [110.5, 60, 40, 21]}
    items = list(flatten(window(button), 2940 / 1470, SCREEN))
    assert (items[1]["x"], items[1]["y"]) == (261, 141)
    assert [item["depth"] for item in items] == [0, 1]


def test_an_element_outside_its_scroll_area_is_not_visible():
    rows = [{"role": "AXStaticText", "value": f"Row {i}", "frame": [100, 60 + 100 * i, 300, 20]} for i in range(3)]
    area = {"role": "AXScrollArea", "frame": [100, 50, 300, 150], "children": rows}
    items = list(flatten(window(area), 1, SCREEN))
    assert [item["visible"] for item in items if item["role"] == "AXStaticText"] == [True, True, False]


def test_labels_match_exact_first_then_contains_ignoring_case():
    items = list(flatten(window(
        {"role": "AXButton", "description": "Save as PDF", "frame": [110, 60, 40, 20]},
        {"role": "AXButton", "title": "save", "frame": [160, 60, 40, 20]},
        {"role": "AXStaticText", "value": "Saved", "frame": [210, 60, 40, 20]},
        {"role": "AXTextField", "label": "Email", "frame": [110, 100, 200, 20]},
    ), 1, SCREEN))
    assert [e.get("title") or e.get("description") or e.get("value") for e in matches(items, "SAVE")] == \
        ["save", "Save as PDF", "Saved"]
    assert [e["role"] for e in matches(items, "save", role="button")] == ["AXButton", "AXButton"]
    assert [e["role"] for e in matches(items, "email", role="AXTextField")] == ["AXTextField"]


def test_hidden_elements_and_subroles():
    items = list(flatten(window(
        {"role": "AXButton", "subrole": "AXCloseButton", "description": "close", "frame": [110, 60, 16, 16]},
        {"role": "AXButton", "title": "close", "frame": [900, 60, 40, 20]},
    ), 1, SCREEN))
    assert [e["subrole"] for e in matches(items, "close")] == ["AXCloseButton"]
    assert len(matches(items, "close", role="AXCloseButton")) == 1
