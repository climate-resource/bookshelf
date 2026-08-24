"""Quality-control station observations, and record the result if a bundle is asked for.

This is an ordinary script rather than a recipe and a build file.
It has its own command line, it writes its own report, and it runs to completion with no
Bookshelf involvement at all unless ``--bundle`` is passed.
The recording is the last dozen lines, which is the point of the example:
a pipeline that already exists does not have to be restructured to publish from.
"""

from pathlib import Path

import pandas as pd
import typer

HERE = Path(__file__).parent
MONTHS_PER_STATION = 3
VOLUME = "low-level-api-example"
VERSION = "v1.0.0"
CODE_REF = "https://example.invalid/examples@0000000000000000000000000000000000000000"
RUNNER = "examples"


def load(path: Path) -> pd.DataFrame:
    """Read the raw station file and put the columns into the types the rest of the script wants."""
    frame = pd.read_csv(path)
    return frame.astype({"station": "string", "year": "int64", "month": "int64", "flag": "string"})


def check(frame: pd.DataFrame) -> list[str]:
    """Return one complaint per thing wrong with the raw file.

    A real pipeline spends most of its length here, and none of it concerns Bookshelf.
    """
    complaints = []
    expected = {"station", "year", "month", "temperature", "flag"}
    if missing := expected - set(frame.columns):
        complaints.append(f"missing columns: {', '.join(sorted(missing))}")
    if frame["temperature"].isna().any():
        complaints.append("temperature has gaps")
    for station, months in frame.groupby("station")["month"].nunique().items():
        if months != MONTHS_PER_STATION:
            complaints.append(f"station {station} has {months} months rather than {MONTHS_PER_STATION}")
    return complaints


def quality_control(frame: pd.DataFrame) -> pd.DataFrame:
    """Drop the readings the provider flagged and keep the ones that survive."""
    return frame[frame["flag"] == "ok"].drop(columns="flag").reset_index(drop=True)


def annual_means(frame: pd.DataFrame) -> pd.DataFrame:
    """Average each station's surviving readings within a year."""
    means = frame.groupby(["station", "year"], as_index=False)["temperature"].mean()
    return means.assign(temperature=lambda f: f["temperature"].round(3))


def anomalies(means: pd.DataFrame) -> pd.DataFrame:
    """Express each annual mean as a departure from that station's own average."""
    baseline = means.groupby("station")["temperature"].transform("mean")
    return means.assign(anomaly=(means["temperature"] - baseline).round(3)).drop(columns="temperature")


def report(raw: pd.DataFrame, kept: pd.DataFrame, means: pd.DataFrame, path: Path) -> None:
    """Write the summary the operators of this pipeline actually read."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"read {len(raw)} readings from {raw['station'].nunique()} stations",
        f"dropped {len(raw) - len(kept)} flagged readings",
        f"wrote {len(means)} station years",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def record(means: pd.DataFrame, anomaly: pd.DataFrame, bundle_path: Path) -> None:
    """Record the two outputs into a reviewable bundle.

    ``RecordingBookshelf`` is the ordinary facade with the producer seam rebound,
    so ``activity()``, ``draft_book()`` and ``register_external()`` land in the bundle
    rather than reaching the API. Recording needs no credentials, and replaying the
    bundle later is the half that does.
    """
    # Imported here rather than at the top, so the pipeline runs without the SDK installed.
    from bookshelf.publisher import Bundle, RecordingBookshelf  # noqa: PLC0415

    bundle = Bundle(bundle_path)
    bs = RecordingBookshelf(
        bundle,
        auth=None,
        authors=[{"name": "Climate Resource", "email": "info@climate-resource.com"}],
    )
    draft = bs.draft_book(
        VOLUME,
        version=VERSION,
        license="CC-BY-4.0",
        visibility="public",
        description="Quality-controlled station temperatures and their anomalies.",
        discovery={"title": "Station observations recorded from a script", "publisher": "Climate Resource"},
    )
    # Opening the activity directly is what lets the script state its own provenance.
    with bs.activity(kind="process", code_ref=CODE_REF, runner=RUNNER, config={"flag": "ok"}) as activity:
        means_resource = activity.register(means, type="timeseries", name="annual-means")
        anomaly_resource = activity.register(
            anomaly, type="timeseries", name="anomalies", used=[means_resource]
        )
    draft.attach(means_resource, name_in_book="annual-means")
    draft.attach(anomaly_resource, name_in_book="anomalies")
    draft.publish()
    bundle.validate()
    bundle.write()


app = typer.Typer(help=__doc__.splitlines()[0])


@app.command()
def main(
    input: Path = typer.Option(HERE / "inputs" / "observations.csv", "--input", help="Raw station file."),
    report_path: Path | None = typer.Option(None, "--report", help="Where to write the run summary."),
    bundle: Path | None = typer.Option(
        None, "--bundle", help="Record the outputs into this bundle directory. The pipeline runs without it."
    ),
) -> None:
    """Quality-control the station file, and record the outputs when a bundle is asked for."""
    raw = load(input)
    if complaints := check(raw):
        for complaint in complaints:
            typer.echo(f"error: {complaint}", err=True)
        raise typer.Exit(code=1)

    kept = quality_control(raw)
    means = annual_means(kept)
    anomaly = anomalies(means)

    if report_path is not None:
        report(raw, kept, means, report_path)

    if bundle is not None:
        record(means, anomaly, bundle)
        typer.echo(f"recorded {VOLUME} {VERSION} into {bundle}")


if __name__ == "__main__":
    app()
