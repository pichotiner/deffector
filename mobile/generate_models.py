"""Генерация Kotlin-моделей из замороженного OpenAPI; контракт не изменяется."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def generate():
    schemas = json.loads((ROOT.parent / "backend/openapi.json").read_text(encoding="utf-8"))["components"]["schemas"]

    def kind(p):
        if "$ref" in p:
            return p["$ref"].split("/")[-1]
        if "anyOf" in p:
            options = p["anyOf"]
            return kind(next(v for v in options if v.get("type") != "null")) + "?"
        return {"string": lambda: "String", "integer": lambda: "Int", "number": lambda: "Double",
                "boolean": lambda: "Boolean", "array": lambda: "List<" + kind(p["items"]) + ">"}[p["type"]]()

    lines = ["// Создано generate_models.py из backend/openapi.json.\npackage ru.kst.deffector\n",
             "import kotlinx.serialization.Serializable\n"]
    for name, schema in schemas.items():
        if name.startswith(("Body_", "HTTPValidation", "ValidationError")):
            continue
        if "properties" not in schema:
            continue
        fields = []
        for field, spec in schema["properties"].items():
            typ = kind(spec)
            default = " = null" if typ.endswith("?") else ""
            if "default" in spec and spec["default"] is not None:
                default = " = " + json.dumps(spec["default"], ensure_ascii=False)
            fields.append(f"    val {field}: {typ}{default}")
        lines.append("@Serializable\ndata class " + name + "(\n" + ",\n".join(fields) + "\n)\n")
    return "\n".join(lines)


if __name__ == "__main__":
    dest = ROOT / "app/src/main/java/ru/kst/deffector/Models.kt"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(generate(), encoding="utf-8")
    print(dest)
