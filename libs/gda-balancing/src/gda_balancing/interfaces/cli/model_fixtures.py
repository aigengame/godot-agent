"""Shared CLI conformance documents for Model commands."""

VALID_MODEL_SOURCE = """{
  "schema_version": "2.0.0",
  "manifest": {"id": "example.quantity-model", "version": "1.0.0", "entry_module": "main"},
  "package_requirements": [{"id": "core.quantity", "version": "2.2.0"}],
  "modules": [{
    "id": "main",
    "imports": [{"alias": "quantity", "package": "core.quantity", "version": "2.2.0", "symbol": "Quantity"}],
    "symbols": [
      {"symbol":"constant_value","type":"quantity","role":"constant","representation":"Int","kind":"scalar","unit":"1","domain_kind":"closed-interval","domain":{"minimum":0,"maximum":100},"numeric_policy":"exact-int64","value_policy":{"mode":"model-fixed","value":1}},
      {"symbol":"parameter_value","type":"quantity","role":"parameter","representation":"Int","kind":"scalar","unit":"1","domain_kind":"closed-interval","domain":{"minimum":0,"maximum":100},"numeric_policy":"exact-int64","value_policy":{"mode":"experiment-required"}},
      {"symbol":"input_value","type":"quantity","role":"input","representation":"Int","kind":"scalar","unit":"1","domain_kind":"closed-interval","domain":{"minimum":0,"maximum":100},"numeric_policy":"exact-int64","value_policy":{"mode":"experiment-required"}},
      {"symbol":"state_value","type":"quantity","role":"state","representation":"Int","kind":"scalar","unit":"1","domain_kind":"closed-interval","domain":{"minimum":0,"maximum":100},"numeric_policy":"exact-int64","value_policy":{"mode":"experiment-required"}},
      {"symbol":"derived_value","type":"quantity","role":"derived","representation":"Int","kind":"scalar","unit":"1","domain_kind":"closed-interval","domain":{"minimum":0,"maximum":100},"numeric_policy":"exact-int64","value_policy":{"mode":"none"}},
      {"symbol":"output_value","type":"quantity","role":"output","representation":"Int","kind":"scalar","unit":"1","domain_kind":"closed-interval","domain":{"minimum":0,"maximum":100},"numeric_policy":"exact-int64","value_policy":{"mode":"none"}},
      {"symbol":"random_value","type":"quantity","role":"random","representation":"Int","kind":"scalar","unit":"1","domain_kind":"closed-interval","domain":{"minimum":0,"maximum":100},"numeric_policy":"exact-int64","value_policy":{"mode":"named-stream"}}
    ]
  }],
  "entrypoints": []
}"""
