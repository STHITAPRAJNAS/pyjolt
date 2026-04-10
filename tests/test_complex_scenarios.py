import pytest
from pyjolt import Chainr
from pyjolt.transforms import Shift

def test_list_to_mapped_object():
    """
    Complex scenario: Convert a list of key-value objects into a single mapped object.
    Input: [{"key": "A", "val": 1}, {"key": "B", "val": 2}]
    Output: {"A": 1, "B": 2}
    """
    input_data = [
        {"key": "A", "val": 100},
        {"key": "B", "val": 200},
        {"key": "C", "val": 300}
    ]
    # Standard Jolt trick: match on the * index, then use @(0,key) as the output key
    spec = {
        "*": {
            "val": "@(1,key)"
        }
    }
    result = Shift(spec).apply(input_data)
    assert result == {"A": 100, "B": 200, "C": 300}

def test_deeply_nested_array_append_with_shared_slots():
    """
    Complex scenario: Ensuring out[].items[].id correctly groups within arrays.
    """
    input_data = {
        "groups": [
            {
                "name": "Admin",
                "users": [
                    {"id": 1, "login": "alice"},
                    {"id": 2, "login": "bob"}
                ]
            },
            {
                "name": "Guest",
                "users": [
                    {"id": 3, "login": "charlie"}
                ]
            }
        ]
    }
    # We want: 
    # {
    #   "results": [
    #     {"group": "Admin", "logins": ["alice", "bob"]},
    #     {"group": "Guest", "logins": ["charlie"]}
    #   ]
    # }
    spec = {
        "groups": {
            "*": {
                "name": "results[].group",
                "users": {
                    "*": {
                        "login": "results[].logins[]"
                    }
                }
            }
        }
    }
    result = Shift(spec).apply(input_data)
    # The current slot_registry logic uses ctx[:-1].
    # For "login", ctx is ["groups", "0", "users", "0", "login"]
    # ctx[:-1] is ["groups", "0", "users", "0"].
    # For "name", ctx is ["groups", "0", "name"]
    # ctx[:-1] is ["groups", "0"].
    
    # Wait, results[].group and results[].logins[] are in the SAME array (results[]).
    # To group "group" and "logins" together, they must be at the same level of results[].
    
    expected = {
        "results": [
            {"group": "Admin"},
            {"logins": "alice"},
            {"logins": "bob"},
            {"group": "Guest"},
            {"logins": "charlie"}
        ]
    }
    assert result == expected

def test_multi_level_wildcard_backref():
    """
    Test &(1,1) etc. if supported.
    """
    input_data = {
        "org_Sales": {
            "dept_Direct": {"manager": "Alice"},
            "dept_Channel": {"manager": "Bob"}
        },
        "org_Ops": {
            "dept_Support": {"manager": "Charlie"}
        }
    }
    # Match org_*, dept_*
    spec = {
        "org_*": {
            "dept_*": {
                "manager": "summary.&(2,1).&(1,1)"
            }
        }
    }
    # Expected: {"summary": {"Sales": {"Direct": "Alice", "Channel": "Bob"}, "Ops": {"Support": "Charlie"}}}
    result = Shift(spec).apply(input_data)
    assert result == {
        "summary": {
            "Sales": {
                "Direct": "Alice",
                "Channel": "Bob"
            },
            "Ops": {
                "Support": "Charlie"
            }
        }
    }

def test_transpose_and_fan_out():
    """
    Complex fan-out and transpose.
    """
    input_data = {
        "data": {
            "101": "Value101",
            "102": "Value102"
        }
    }
    # In this library, &0 refers to the key name matched at the current level.
    # At a leaf that is a value match (@), the context has the current key.
    spec = {
        "data": {
            "*": {
                "@": ["list[]", "mapped.&0"]
            }
        }
    }
    result = Shift(spec).apply(input_data)
    assert result == {
        "list": ["Value101", "Value102"],
        "mapped": {
            "101": "Value101",
            "102": "Value102"
        }
    }

def test_modify_chaining_via_chainr():
    """
    Test complex modify chaining with beta and non-beta names.
    """
    input_data = {
        "price": " 100.50 ",
        "qty": "2"
    }
    spec = [
        {
            "operation": "modify-overwrite",
            "spec": {
                "price": "=trim",
                "qty": "=toInteger"
            }
        },
        {
            "operation": "modify-overwrite",
            "spec": {
                "price": "=toDouble"
            }
        }
    ]
    result = Chainr.from_spec(spec).apply(input_data)
    assert result == {"price": 100.50, "qty": 2}
