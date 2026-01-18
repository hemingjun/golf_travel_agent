"""State Reducer 单元测试"""

import sys
sys.path.insert(0, "src")

from travel_agent.graph.state import merge_trip_data


def test_merge_update_existing():
    """测试：更新已存在的记录"""
    current = {"golf_bookings": [{"id": "1", "name": "A球场"}]}
    update = {"golf_bookings": [{"id": "1", "name": "A球场(已更新)"}]}

    result = merge_trip_data(current, update)

    assert len(result["golf_bookings"]) == 1
    assert result["golf_bookings"][0]["name"] == "A球场(已更新)"


def test_merge_append_new():
    """测试：追加新记录"""
    current = {"golf_bookings": [{"id": "1", "name": "A球场"}]}
    update = {"golf_bookings": [{"id": "2", "name": "B球场"}]}

    result = merge_trip_data(current, update)

    assert len(result["golf_bookings"]) == 2


def test_merge_update_and_append():
    """测试：同时更新和追加"""
    current = {"golf_bookings": [{"id": "1", "name": "A球场"}]}
    update = {
        "golf_bookings": [
            {"id": "1", "name": "A球场(已更新)"},
            {"id": "2", "name": "B球场"}
        ]
    }

    result = merge_trip_data(current, update)

    assert len(result["golf_bookings"]) == 2
    assert result["golf_bookings"][0]["name"] == "A球场(已更新)"
    assert result["golf_bookings"][1]["name"] == "B球场"


def test_merge_preserves_extra_fields():
    """测试：更新时保留原有字段"""
    current = {"golf_bookings": [{"id": "1", "name": "A球场", "address": "地址1"}]}
    update = {"golf_bookings": [{"id": "1", "name": "A球场(已更新)"}]}

    result = merge_trip_data(current, update)

    assert result["golf_bookings"][0]["address"] == "地址1"
    assert result["golf_bookings"][0]["name"] == "A球场(已更新)"


def test_merge_empty_current():
    """测试：当前状态为空"""
    current = {}
    update = {"golf_bookings": [{"id": "1", "name": "A球场"}]}

    result = merge_trip_data(current, update)

    assert len(result["golf_bookings"]) == 1


def test_merge_none_values():
    """测试：None 值处理"""
    assert merge_trip_data(None, {"a": 1}) == {"a": 1}
    assert merge_trip_data({"a": 1}, None) == {"a": 1}


def test_merge_simple_list():
    """测试：简单值列表去重"""
    current = {"tags": ["golf", "hotel"]}
    update = {"tags": ["hotel", "logistics"]}

    result = merge_trip_data(current, update)

    assert set(result["tags"]) == {"golf", "hotel", "logistics"}


if __name__ == "__main__":
    test_merge_update_existing()
    test_merge_append_new()
    test_merge_update_and_append()
    test_merge_preserves_extra_fields()
    test_merge_empty_current()
    test_merge_none_values()
    test_merge_simple_list()
    print("✓ 所有测试通过")
