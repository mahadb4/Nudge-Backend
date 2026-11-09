"""ARCHITECTURE 10 and docs/CODING_STYLE.md: layer rules, file names, naming, scale rules and the
no-magic-strings rule.

Everything is checked on the source code (AST). Each rule is a small checker function that takes
source text,
and the checker is itself tested on a deliberately bad snippet, so a passing run proves the rule
can fail.
"""

import ast
import re
from pathlib import Path

import pytest
from django.conf import settings

from common.constants import Limits
from common.messages import Messages

ROOT = Path(settings.BASE_DIR)
SOURCE_ROOTS = [ROOT / "common", ROOT / "apps", ROOT / "config"]
FRAMEWORKS = ("django", "rest_framework", "psycopg")

# Every module (common/health and each app) has these folders. Apps also have tests/.
LAYER_FOLDERS = ["api", "dtos", "mappers", "repositories", "services", "domain"]
SINGLE_FILE_NAMES = ["dtos.py", "mappers.py", "services.py", "repositories.py"]

# Allowed file names per folder (CODING_STYLE 1). A pattern must match the whole file name.
FILE_NAME_RULES = {
    "api": [r"urls\.py", r"[a-z_]+_api\.py"],
    "dtos": [r"[a-z_]+_dtos\.py"],
    "mappers": [r"[a-z_]+_mapper\.py"],
    "repositories": [r"interfaces\.py", r"models\.py", r"[a-z_]+_repository\.py"],
    "services": [r"interfaces\.py", r"[a-z_]+_service\.py", r"[a-z_]+_validator\.py"],
    "domain": [r"entities\.py", r"enums\.py", r"errors\.py", r"defaults\.py"],
    "cache": [r"[a-z_]+_cache\.py"],
    "tests": [r"test_[a-z0-9_]+\.py", r"fakes\.py", r"conftest\.py"],
}
CLASS_SUFFIX_RULES = {
    "api": ("Api",),
    "services": ("Service", "Validator"),
    "repositories": ("Repository", "Model"),
}

# Shared files every layer may use, so they must not depend on a framework.
FRAMEWORK_FREE = [
    "common/messages.py",
    "common/errors.py",
    "common/constants.py",
    "common/interfaces.py",
    "common/text.py",
    "common/validators.py",
    "common/dtos.py",
    "common/infra/clock.py",
    "common/health/domain/entities.py",
    "common/health/dtos/health_dtos.py",
    "common/health/mappers/health_mapper.py",
    "common/health/repositories/interfaces.py",
    "common/health/services/health_service.py",
]

ERROR_CLASSES = {
    "AppError",
    "ValidationFailed",
    "Unauthorized",
    "Forbidden",
    "NotFound",
    "MethodNotAllowed",
    "Conflict",
    "RateLimited",
    "ServiceUnavailable",
    "InvalidValue",
    "TestDatabaseRefused",
}
# Collected from the catalogue itself, so any future member is covered without editing this test.
MESSAGE_NAMES = set(Messages.__members__)
MESSAGE_TEXTS = {message.value for message in Messages}

WILDCARD_ALWAYS = {"delete_pattern", "scan_iter", "flushdb", "flushall"}
WILDCARD_ON_CACHE = {"keys", "scan", "clear"}
CAPPED_PAGINATION_HELPERS = ("parse_page_params(", "parse_list_query(", "parse_cursor_params(")
CONSTANT_NAME = re.compile(r"_?[A-Z][A-Z0-9_]*")
DJANGO_REQUIRED_GLOBALS = {"__all__", "urlpatterns"}  # Django looks these up by name


# ---------------------------------------------------------------- finding files


def app_modules() -> list[Path]:
    return sorted(p for p in (ROOT / "apps").iterdir() if p.is_dir() and not p.name.startswith("_"))


def modules() -> list[Path]:
    return [ROOT / "common" / "health", *app_modules()]


def python_files(*roots: Path) -> list[Path]:
    return [p for root in roots for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def is_test_file(path: Path) -> bool:
    return "tests" in path.relative_to(ROOT).parts or path.name == "conftest.py"


def source_files() -> list[Path]:
    """Production code: common/, apps/ and config/, without tests."""
    return [p for p in python_files(*SOURCE_ROOTS) if not is_test_file(p)]


def layer_files(layer: str) -> list[Path]:
    found: list[Path] = []
    for module in modules():
        folder = module / layer
        if folder.is_dir():
            found.extend(python_files(folder))
    return found


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def imported_modules(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(parse(path)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def imports_any(path: Path, *fragments: str) -> set[str]:
    return {m for m in imported_modules(path) if any(f in m for f in fragments)}


# ---------------------------------------------------------------- checkers (source text -> list of
# problems)


def check_status_literals(source: str) -> list[str]:
    """HTTP status codes come from named constants (HTTPStatus), never from number literals."""
    problems = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.keyword) and node.arg == "status" and _is_int(node.value):
            problems.append(f"line {node.value.lineno}: status={node.value.value}")
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == "status" for t in targets) and _is_int(
                node.value
            ):
                problems.append(f"line {node.lineno}: status = {node.value.value}")
    return problems


def _is_int(node: ast.AST | None) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
    )


def check_type_hints(source: str) -> list[str]:
    """Type hints on every function signature (CODING_STYLE 5)."""
    problems = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = node.args
        every = [
            *args.posonlyargs,
            *args.args,
            *args.kwonlyargs,
            *filter(None, [args.vararg, args.kwarg]),
        ]
        missing = [a.arg for a in every if a.annotation is None and a.arg not in ("self", "cls")]
        if missing:
            problems.append(f"line {node.lineno}: {node.name} has unannotated {missing}")
        if node.returns is None:
            problems.append(f"line {node.lineno}: {node.name} has no return type")
    return problems


def check_exception_handling(source: str) -> list[str]:
    """No bare except and no except Exception (CODING_STYLE 4). Catch the specific error."""
    problems = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ExceptHandler):
            name = node.type.id if isinstance(node.type, ast.Name) else None
            if node.type is None or name in ("Exception", "BaseException"):
                problems.append(f"line {node.lineno}: except {name or ''}")
    return problems


def check_service_raises(source: str) -> list[str]:
    """Services raise AppError subclasses only, never ValueError and friends (CODING_STYLE 2)."""
    problems = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Raise) and node.exc is not None:
            call = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            name = call.id if isinstance(call, ast.Name) else ""
            if name in ("ValueError", "Exception", "KeyError", "RuntimeError", "TypeError"):
                problems.append(f"line {node.lineno}: raise {name}")
    return problems


def check_wildcard_cache(source: str) -> list[str]:
    """No wildcard cache deletes: no KEYS or SCAN, no delete_pattern, no clear (CODING_STYLE 7)."""
    problems = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr, receiver = node.func.attr, ast.unparse(node.func.value).lower()
            if attr in WILDCARD_ALWAYS or (
                attr in WILDCARD_ON_CACHE and ("cache" in receiver or "redis" in receiver)
            ):
                problems.append(f"line {node.lineno}: {receiver}.{attr}()")
    return problems


def check_module_state(source: str) -> list[str]:
    """Stateless API: no mutable module-level state. Constants (UPPER_CASE names) are fine."""
    problems = []
    for node in ast.parse(source).body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        mutable = isinstance(node.value, (ast.Dict, ast.List, ast.Set)) or (
            isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id
            in ("dict", "list", "set", "defaultdict", "OrderedDict", "deque", "Counter")
        )
        for target in targets:
            if (
                mutable
                and isinstance(target, ast.Name)
                and not CONSTANT_NAME.fullmatch(target.id)
                and target.id not in DJANGO_REQUIRED_GLOBALS
            ):
                problems.append(f"line {node.lineno}: module-level mutable {target.id}")
    return problems


def check_list_apis_are_capped(source: str) -> list[str]:
    """Every *ListApi class must read its page size through a helper that enforces the hard cap."""
    problems = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name.endswith("ListApi"):
            body = ast.get_source_segment(source, node) or ""
            if not any(helper in body for helper in CAPPED_PAGINATION_HELPERS):
                problems.append(
                    f"{node.name} does not call {' or '.join(CAPPED_PAGINATION_HELPERS)}"
                )
    return problems


def check_cache_keys_have_organization(source: str) -> list[str]:
    """In cache/ modules every key-building function takes organization_id (CODING_STYLE 7)."""
    problems = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name.endswith("_key"):
            names = [
                a.arg for a in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
            ]
            if "organization_id" not in names:
                problems.append(f"line {node.lineno}: {node.name} has no organization_id parameter")
    return problems


def check_tenant_repository_methods(source: str) -> list[str]:
    """Every public method of a TenantRepository subclass takes `context` first (BACKEND_PLAN 2)."""
    problems = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ClassDef):
            continue
        if not any(ast.unparse(base).startswith("TenantRepository") for base in node.bases):
            continue
        for method in node.body:
            if isinstance(method, ast.FunctionDef) and not method.name.startswith("_"):
                names = [a.arg for a in method.args.args if a.arg != "self"]
                if not names or names[0] != "context":
                    problems.append(f"line {method.lineno}: {node.name}.{method.name}")
    return problems


def check_mappers_are_functions(source: str) -> list[str]:
    return [
        f"line {n.lineno}: class {n.name}"
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.ClassDef)
    ]


def check_domain_dataclasses_are_frozen(source: str) -> list[str]:
    problems = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef):
            for decorator in node.decorator_list:
                is_dataclass = (
                    isinstance(decorator, ast.Name) and decorator.id == "dataclass"
                ) or (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Name)
                    and decorator.func.id == "dataclass"
                )
                frozen = isinstance(decorator, ast.Call) and any(
                    k.arg == "frozen"
                    and isinstance(k.value, ast.Constant)
                    and k.value.value is True
                    for k in decorator.keywords
                )
                if is_dataclass and not frozen:
                    problems.append(f"line {node.lineno}: dataclass {node.name} is not frozen")
    return problems


def check_class_name_suffixes(source: str, suffixes: tuple[str, ...]) -> list[str]:
    problems = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef) and not node.name.endswith(suffixes):
            problems.append(
                f"line {node.lineno}: class {node.name} should end with {' or '.join(suffixes)}"
            )
    return problems


def run(checker, paths: list[Path], *extra) -> list[str]:
    problems = []
    for path in paths:
        problems += [f"{rel(path)}: {p}" for p in checker(path.read_text(encoding="utf-8"), *extra)]
    return problems


# ---------------------------------------------------------------- the checkers can fail (tested on
# bad snippets)


@pytest.mark.parametrize(
    ("checker", "bad", "good"),
    [
        (
            check_status_literals,
            "x = Response(data, status=201)",
            "x = Response(data, status=HTTPStatus.CREATED)",
        ),
        (
            check_status_literals,
            "class A:\n    status = 404",
            "class A:\n    status = HTTPStatus.NOT_FOUND",
        ),
        (
            check_type_hints,
            "def f(a, b: int) -> int:\n    return b",
            "def f(self, a: int) -> int:\n    return a",
        ),
        (
            check_type_hints,
            "def f(a: int):\n    return a",
            "def f(a: int) -> None:\n    return None",
        ),
        (
            check_exception_handling,
            "try:\n    x()\nexcept Exception:\n    pass",
            "try:\n    x()\nexcept OSError:\n    pass",
        ),
        (
            check_exception_handling,
            "try:\n    x()\nexcept:\n    pass",
            "try:\n    x()\nexcept (OSError, ValueError):\n    pass",
        ),
        (
            check_service_raises,
            "def f():\n    raise ValueError('x')",
            "def f():\n    raise NotFound()",
        ),
        (check_wildcard_cache, "cache.delete_pattern('a:*')", "cache.delete('a:1')"),
        (check_wildcard_cache, "self._redis.keys('a:*')", "mapping.keys()"),
        (check_wildcard_cache, "self._cache.clear()", "values.clear()"),
        (check_module_state, "seen = {}", "SEEN = frozenset()"),
        (check_module_state, "_items: list = []", "_DEFAULTS = {'a': 1}"),
        (
            check_list_apis_are_capped,
            "class CompanyListApi:\n    def get(self):\n        return all()",
            "class CompanyListApi:\n    def get(self):\n        q = parse_page_params(request)",
        ),
        (
            check_cache_keys_have_organization,
            "def company_list_key(page):\n    return page",
            "def company_list_key(organization_id, page):\n    return page",
        ),
        (
            check_tenant_repository_methods,
            "class XRepository(TenantRepository[M]):\n    def get(self, id):\n        return 1",
            "class XRepository(TenantRepository[M]):\n"
            "    def get(self, context, id):\n"
            "        return 1",
        ),
        (
            check_mappers_are_functions,
            "class UserMapper:\n    pass",
            "def to_x(a: int) -> int:\n    return a",
        ),
        (
            check_domain_dataclasses_are_frozen,
            "@dataclass\nclass User:\n    id: int",
            "@dataclass(frozen=True, slots=True)\nclass User:\n    id: int",
        ),
    ],
    ids=lambda v: v.__name__ if callable(v) else None,
)
def test_each_checker_flags_bad_code_and_accepts_good_code(checker, bad, good):
    assert checker(bad), "the checker did not flag a deliberately bad snippet"
    assert not checker(good), checker(good)


def test_class_name_checker():
    assert check_class_name_suffixes("class Foo:\n    pass", ("Api",))
    assert not check_class_name_suffixes("class FooApi:\n    pass", ("Api",))


# ---------------------------------------------------------------- layers


@pytest.mark.parametrize("name", FRAMEWORK_FREE)
def test_shared_modules_are_framework_free(name):
    bad = {m for m in imported_modules(ROOT / name) if m.split(".")[0] in FRAMEWORKS}
    assert not bad, f"{name} imports {bad}"


def test_services_and_domain_are_framework_free():
    for path in [*layer_files("services"), *layer_files("domain")]:
        bad = {m for m in imported_modules(path) if m.split(".")[0] in FRAMEWORKS}
        assert not bad, f"{rel(path)} imports {bad}"


def test_api_does_not_import_repositories():
    for path in layer_files("api"):
        bad = imports_any(path, ".repositories")
        assert not bad, f"{rel(path)} imports {bad}"


def test_services_do_not_import_api():
    for path in layer_files("services"):
        assert not imports_any(path, ".api"), rel(path)


def test_repositories_do_not_import_services_or_api():
    for path in layer_files("repositories"):
        bad = imports_any(path, ".services", ".api")
        assert not bad, f"{rel(path)} imports {bad}"


def test_only_repositories_import_the_orm_models():
    """ORM objects never leave the repository: nothing else may import repositories/models.py."""
    for path in source_files():
        if "repositories" in path.parts:
            continue
        assert not imports_any(path, "repositories.models"), rel(path)


# ---------------------------------------------------------------- folders and file names


def test_there_are_modules_to_check():
    assert {"accounts", "crm", "audit"} <= {m.name for m in app_modules()}


@pytest.mark.parametrize("module", modules(), ids=lambda m: m.name)
def test_every_module_has_the_standard_folders(module):
    wanted = [*LAYER_FOLDERS, *(["tests"] if module.parent.name == "apps" else [])]
    missing = [f for f in wanted if not (module / f / "__init__.py").is_file()]
    assert not missing, f"{rel(module)} is missing {missing}"


@pytest.mark.parametrize("module", modules(), ids=lambda m: m.name)
def test_no_single_file_instead_of_a_folder(module):
    found = [name for name in SINGLE_FILE_NAMES if (module / name).exists()]
    assert not found, f"{rel(module)} has {found}; use the folders instead"


def test_file_names_follow_the_style_guide():
    offenders = []
    for module in modules():
        for folder, patterns in FILE_NAME_RULES.items():
            directory = module / folder
            if not directory.is_dir():
                continue
            for path in directory.glob("*.py"):
                if path.name != "__init__.py" and not any(
                    re.fullmatch(p, path.name) for p in patterns
                ):
                    offenders.append(f"{rel(path)} (allowed: {patterns})")
    assert not offenders, offenders


def test_class_names_follow_the_style_guide():
    problems = []
    for folder, suffixes in CLASS_SUFFIX_RULES.items():
        for path in layer_files(folder):
            if path.name in ("interfaces.py", "urls.py") or path.name == "__init__.py":
                continue
            problems += [
                f"{rel(path)}: {p}"
                for p in check_class_name_suffixes(path.read_text(encoding="utf-8"), suffixes)
            ]
    assert not problems, problems


def test_protocols_in_interfaces_are_named_like_the_thing_they_describe():
    """interfaces.py holds Protocols; they must not be called XxxProtocol or IXxx."""
    for folder in ("repositories", "services"):
        for path in layer_files(folder):
            if path.name == "interfaces.py":
                for node in parse(path).body:
                    if isinstance(node, ast.ClassDef):
                        assert not node.name.startswith("I") or not node.name[1:2].isupper(), (
                            node.name
                        )
                        assert not node.name.endswith("Protocol"), node.name


def test_mappers_are_plain_functions():
    assert not run(check_mappers_are_functions, layer_files("mappers"))


def test_domain_dataclasses_are_frozen():
    assert not run(check_domain_dataclasses_are_frozen, layer_files("domain"))


# ---------------------------------------------------------------- style rules on all production
# code


def test_status_codes_use_named_constants():
    assert not run(check_status_literals, source_files())


def test_every_function_has_type_hints():
    assert not run(check_type_hints, source_files())


def test_no_bare_or_blanket_except():
    assert not run(check_exception_handling, source_files())


def test_services_raise_only_app_errors():
    assert not run(check_service_raises, layer_files("services"))


# ---------------------------------------------------------------- scale rules (CODING_STYLE 7) that
# can be checked


def test_no_wildcard_cache_operations():
    assert not run(check_wildcard_cache, source_files())


def test_no_mutable_module_level_state():
    files = [p for p in source_files() if "config" not in p.relative_to(ROOT).parts]
    assert not run(check_module_state, files)


def test_every_list_api_is_capped():
    assert not run(check_list_apis_are_capped, layer_files("api"))


def test_tenant_repository_methods_take_the_tenant_context_first():
    assert not run(check_tenant_repository_methods, layer_files("repositories"))


def test_cache_keys_include_the_organization():
    paths = (
        [p for m in modules() for p in python_files(m / "cache")]
        if any((m / "cache").is_dir() for m in modules())
        else []
    )
    assert not run(check_cache_keys_have_organization, paths)


def test_the_page_size_cap_is_100():
    assert Limits.PAGE_SIZE_MAX == 100 and Limits.PAGE_SIZE_DEFAULT <= Limits.PAGE_SIZE_MAX


def test_settings_set_the_timeouts_the_scale_rules_ask_for():
    options = settings.DATABASES["default"]["OPTIONS"]
    assert "statement_timeout=" in options["options"]
    assert options["connect_timeout"] <= 10
    assert 0 < settings.EMAIL_TIMEOUT <= 30
    assert settings.DATABASES["default"]["CONN_HEALTH_CHECKS"] is True


# ---------------------------------------------------------------- no magic strings


def test_message_names_come_from_the_catalogue():
    assert "AUTH_BAD_CREDENTIALS" in MESSAGE_NAMES and len(MESSAGE_TEXTS) == len(MESSAGE_NAMES)


def test_no_string_literal_is_passed_to_an_error():
    offenders = []
    for path in python_files(ROOT / "common", ROOT / "apps"):
        for node in ast.walk(parse(path)):
            if not isinstance(node, ast.Call):
                continue
            # Our errors are always imported by name; attribute calls (drf.NotFound) are other
            # libraries.
            name = node.func.id if isinstance(node.func, ast.Name) else ""
            if (
                name in ERROR_CLASSES
                and node.args
                and isinstance(node.args[0], (ast.Constant, ast.JoinedStr))
            ):
                offenders.append(f"{rel(path)}:{node.lineno}")
    assert not offenders, offenders


def test_no_message_name_or_text_literal_outside_messages_py():
    """Tests may assert on literal codes and texts: that is how the wire contract is pinned."""
    offenders = []
    for path in source_files():
        if rel(path) == "common/messages.py":
            continue
        for node in ast.walk(parse(path)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in MESSAGE_NAMES or node.value in MESSAGE_TEXTS:
                    offenders.append(f"{rel(path)}:{node.lineno} {node.value!r}")
    assert not offenders, offenders
