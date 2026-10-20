"""Generated tests must remain valid Python and have a real pass criterion."""

import ast
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from models import Endpoint, TestCase
from writers.pytest_writer import HEADER, _render_case


class PytestWriterTests(unittest.TestCase):
    def setUp(self):
        self.endpoint = Endpoint(
            path='/pets/{id}', method='GET', operation_id=None,
            parameters=[], request_body_schema=None,
        )

    def test_model_text_cannot_escape_generated_literals(self):
        case = TestCase(
            endpoint=self.endpoint, category="negative",
            description='bad """\nimport os\nos.system("echo injected")',
            path_params={"id": 'x"\nimport os'},
            expected_status=404,
        )
        source = HEADER + _render_case(case, 0)
        module = ast.parse(source)
        functions = [node for node in module.body if isinstance(node, ast.FunctionDef)]
        self.assertEqual(len(functions), 1)
        self.assertEqual(ast.get_docstring(functions[0]), case.description)
        self.assertEqual(
            functions[0].body[0].value.value,
            case.description,
        )
        self.assertEqual(
            functions[0].body[1].value.right.value,
            '/pets/x"\nimport os',
        )

        self.endpoint.method = 'GET"\nimport subprocess'
        module = ast.parse(HEADER + _render_case(case, 0))
        functions = [node for node in module.body if isinstance(node, ast.FunctionDef)]
        self.assertEqual(len(functions), 1)
        request_call = next(
            node for node in ast.walk(functions[0])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "request"
        )
        self.assertEqual(request_call.args[0].value, self.endpoint.method.lower())

    def test_missing_oracle_is_skipped_instead_of_passing(self):
        case = TestCase(
            endpoint=self.endpoint, category="edge",
            description="review expected behavior",
        )
        source = _render_case(case, 1)
        self.assertIn("pytest.skip", source)
        self.assertNotIn("requests.request", source)
        self.assertNotIn("assert response is not None", source)

    def test_invalid_model_fields_are_rejected(self):
        for category, status in (("edge;print(1)", 200), ("edge", True),
                                 ("edge", "200"), ("edge", 999)):
            with self.subTest(category=category, status=status):
                case = TestCase(
                    endpoint=self.endpoint, category=category,
                    description="invalid", expected_status=status,
                )
                with self.assertRaises(ValueError):
                    _render_case(case, 0)


if __name__ == "__main__":
    unittest.main()
