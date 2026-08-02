import typer
from dotenv import load_dotenv

from case_generator import generate_cases
from spec_parser import extract_endpoints, load_spec
from writers import WRITERS

load_dotenv()

app = typer.Typer()


@app.command()
def generate(
    spec_path: str = typer.Argument(..., help="Path to an OpenAPI spec (yaml/json)"),
    out: str = typer.Option("generated", help="Output directory"),
    format: str = typer.Option("pytest", help="Comma-separated output formats, e.g. pytest,postman"),
):
    """Generate edge/negative/boundary test cases for an OpenAPI spec."""
    spec = load_spec(spec_path)
    endpoints = extract_endpoints(spec)
    typer.echo(f"Found {len(endpoints)} endpoint(s) in {spec_path}")

    cases = generate_cases(endpoints)
    typer.echo(f"Generated {len(cases)} test case(s)")

    for fmt in format.split(","):
        fmt = fmt.strip()
        if fmt not in WRITERS:
            typer.echo(f"Unknown format '{fmt}', skipping. Available: {list(WRITERS)}")
            continue
        writer = WRITERS[fmt]()
        out_path = writer.write(cases, out)
        typer.echo(f"[{fmt}] wrote {out_path}")


if __name__ == "__main__":
    app()
