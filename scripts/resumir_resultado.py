from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
INPUT_CSV = ROOT_DIR / "resultado_voos.csv"
OUTPUT_SUMMARY = ROOT_DIR / "resumo_resultado.txt"
OUTPUT_OFFERS = ROOT_DIR / "resumo_ofertas.txt"
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S %z"
FLIGHT_DATE_FORMAT = "%d/%m/%Y"
DEFAULT_PRECO_ALVO_EXCELENTE = 230.0
DEFAULT_PRECO_ALVO_BOM = 260.0
DEFAULT_PRECO_ALVO_EVITAR = 400.0


@dataclass
class ResultRow:
    codigo_consulta: str
    processed_at: datetime
    processed_at_raw: str
    origem: str
    destino: str
    data_voo: str
    menor_preco: float
    preco_alvo_excelente: float
    preco_alvo_bom: float
    preco_alvo_evitar: float


@dataclass
class ConsultationSnapshot:
    processed_at: datetime
    processed_at_raw: str
    legs: list[ResultRow]


@dataclass
class LegStatus:
    key: str
    summary: str


@dataclass
class TripHistory:
    latest: ConsultationSnapshot
    previous: ConsultationSnapshot | None


def parse_flight_date(value: str) -> datetime:
    return datetime.strptime(value, FLIGHT_DATE_FORMAT)


def today() -> datetime.date:
    return datetime.now().astimezone().date()


def has_past_leg(rows: list[ResultRow], reference_date: datetime.date) -> bool:
    return any(parse_flight_date(row.data_voo).date() < reference_date for row in rows)


def format_run_timestamp(value: datetime) -> str:
    return value.strftime("%d/%m/%Y %H:%M")


def parse_target(row: dict[str, str], field: str, default: float) -> float:
    raw_value = row.get(field, "").strip()
    if not raw_value:
        return default
    return float(raw_value.replace(",", "."))


def load_rows(csv_path: Path) -> list[ResultRow]:
    rows: list[ResultRow] = []
    with csv_path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            rows.append(
                ResultRow(
                    codigo_consulta=row.get("codigo_consulta", row["data_hora_processamento"]).strip(),
                    processed_at=datetime.strptime(row["data_hora_processamento"], TIMESTAMP_FORMAT),
                    processed_at_raw=row["data_hora_processamento"],
                    origem=row["origem"].strip().upper(),
                    destino=row["destino"].strip().upper(),
                    data_voo=row["data_voo"].strip(),
                    menor_preco=float(row["menor_preco"]),
                    preco_alvo_excelente=parse_target(row, "preco_alvo_excelente", DEFAULT_PRECO_ALVO_EXCELENTE),
                    preco_alvo_bom=parse_target(row, "preco_alvo_bom", DEFAULT_PRECO_ALVO_BOM),
                    preco_alvo_evitar=parse_target(row, "preco_alvo_evitar", DEFAULT_PRECO_ALVO_EVITAR),
                )
            )
    return rows


def build_target_status(row: ResultRow) -> str:
    if row.menor_preco <= row.preco_alvo_excelente:
        return f"🔥 Excelente: BRL {row.menor_preco:.2f} (até BRL {row.preco_alvo_excelente:.2f})"
    if row.menor_preco <= row.preco_alvo_bom:
        return f"👍 Bom: BRL {row.menor_preco:.2f} (até BRL {row.preco_alvo_bom:.2f})"
    if row.menor_preco > row.preco_alvo_evitar:
        return f"🚫 Evitar: BRL {row.menor_preco:.2f} (acima de BRL {row.preco_alvo_evitar:.2f})"
    return (
        f"⚠️ Acima do bom: BRL {row.menor_preco:.2f} "
        f"(bom até BRL {row.preco_alvo_bom:.2f}; evitar acima de BRL {row.preco_alvo_evitar:.2f})"
    )


def is_good_or_better(row: ResultRow) -> bool:
    return row.menor_preco <= row.preco_alvo_bom


def build_total_target_status(rows: list[ResultRow]) -> str:
    total_price = sum(row.menor_preco for row in rows)
    total_excellent = sum(row.preco_alvo_excelente for row in rows)
    total_good = sum(row.preco_alvo_bom for row in rows)
    total_avoid = sum(row.preco_alvo_evitar for row in rows)

    if total_price <= total_excellent:
        return f"🔥 Excelente: BRL {total_price:.2f} (até BRL {total_excellent:.2f})"
    if total_price <= total_good:
        return f"👍 Bom: BRL {total_price:.2f} (até BRL {total_good:.2f})"
    if total_price > total_avoid:
        return f"🚫 Evitar: BRL {total_price:.2f} (acima de BRL {total_avoid:.2f})"
    return (
        f"⚠️ Acima do bom: BRL {total_price:.2f} "
        f"(bom até BRL {total_good:.2f}; evitar acima de BRL {total_avoid:.2f})"
    )


def build_leg_status(previous: ResultRow | None, latest: ResultRow) -> LegStatus:
    if previous is None:
        return LegStatus("insufficient", f"🆕 Sem historico | BRL {latest.menor_preco:.2f}")

    delta = round(latest.menor_preco - previous.menor_preco, 2)
    if delta > 0:
        return LegStatus(
            "higher",
            f"🔴 Mais alto +BRL {delta:.2f} | de BRL {previous.menor_preco:.2f} para BRL {latest.menor_preco:.2f}",
        )
    if delta < 0:
        return LegStatus(
            "lower",
            f"🟢 Mais baixo -BRL {abs(delta):.2f} | de BRL {previous.menor_preco:.2f} para BRL {latest.menor_preco:.2f}",
        )
    return LegStatus("stable", f"⚪ Igual | BRL {latest.menor_preco:.2f}")


def get_latest_trip_histories(rows: list[ResultRow]) -> list[TripHistory]:
    reference_date = today()
    latest_processed_at = max(row.processed_at for row in rows)
    grouped: dict[str, list[ResultRow]] = defaultdict(list)
    for row in rows:
        grouped[row.codigo_consulta].append(row)

    trips_by_signature: dict[tuple[tuple[str, str, str], ...], list[ConsultationSnapshot]] = defaultdict(list)
    for consultation_rows in grouped.values():
        if has_past_leg(consultation_rows, reference_date):
            continue

        ordered_legs = sorted(consultation_rows, key=lambda item: (parse_flight_date(item.data_voo), item.origem, item.destino))
        signature = tuple((leg.origem, leg.destino, leg.data_voo) for leg in ordered_legs)
        snapshot = ConsultationSnapshot(
            processed_at=ordered_legs[0].processed_at,
            processed_at_raw=ordered_legs[0].processed_at_raw,
            legs=ordered_legs,
        )
        trips_by_signature[signature].append(snapshot)

    sorted_signatures = sorted(
        trips_by_signature,
        key=lambda signature: tuple(parse_flight_date(leg[2]) for leg in signature),
    )

    histories: list[TripHistory] = []
    for signature in sorted_signatures:
        history = sorted(trips_by_signature[signature], key=lambda item: item.processed_at)
        latest = history[-1]
        if latest.processed_at != latest_processed_at:
            continue

        previous = history[-2] if len(history) > 1 else None
        histories.append(TripHistory(latest=latest, previous=previous))
    return histories


def build_summary(rows: list[ResultRow]) -> str:
    if not rows:
        return "Nenhum dado encontrado em resultado_voos.csv."

    trip_histories = get_latest_trip_histories(rows)
    if not trip_histories:
        return "Nenhum voo futuro encontrado em resultado_voos.csv."

    comparison_blocks: list[str] = []
    stable = 0
    higher = 0
    lower = 0
    insufficient = 0

    for trip_history in trip_histories:
        latest = trip_history.latest
        previous = trip_history.previous
        previous_legs = previous.legs if previous else []
        block_lines: list[str] = []
        first_leg = latest.legs[0]
        last_leg = latest.legs[-1]

        block_lines.append(f"*{first_leg.data_voo} a {last_leg.data_voo}*")

        for index, latest_leg in enumerate(latest.legs):
            leg_label = "Ida" if index == 0 else "Volta" if index == 1 else f"Trecho {index + 1}"
            previous_leg = previous_legs[index] if index < len(previous_legs) else None
            status = build_leg_status(previous_leg, latest_leg)

            if status.key == "higher":
                higher += 1
            elif status.key == "lower":
                lower += 1
            elif status.key == "stable":
                stable += 1
            else:
                insufficient += 1

            block_lines.append(
                f"- {leg_label}: {latest_leg.origem} -> {latest_leg.destino} ({latest_leg.data_voo})"
            )
            block_lines.append(
                f"  {status.summary}"
            )
            block_lines.append(
                f"  📉 Preço alvo: {build_target_status(latest_leg)}"
            )

        block_lines.append(f"- Total ida e volta: {build_total_target_status(latest.legs)}")
        comparison_blocks.append("\n".join(block_lines))

    latest_run = format_run_timestamp(max(row.processed_at for row in rows))
    previous_runs = sorted({row.processed_at for row in rows})
    previous_run_text = (
        format_run_timestamp(previous_runs[-2]) if len(previous_runs) > 1 else "nao ha execucao anterior"
    )

    summary_parts = [
        "*Resumo de precos*",
        f"Atualizado em: {latest_run}",
        f"Comparado com: {previous_run_text}",
        "",
        "*Panorama*",
        f"- Trechos mais baixos: {lower}",
        f"- Trechos mais altos: {higher}",
        f"- Trechos sem alteracao: {stable}",
        f"- Trechos sem historico: {insufficient}",
        "",
        "*Voos*",
        "\n\n".join(comparison_blocks),
    ]
    return "\n".join(summary_parts)


def build_offers_summary(rows: list[ResultRow]) -> str:
    if not rows:
        return "Nenhum dado encontrado em resultado_voos.csv."

    trip_histories = get_latest_trip_histories(rows)
    if not trip_histories:
        return "Nenhum voo futuro encontrado em resultado_voos.csv."

    latest_run = format_run_timestamp(max(row.processed_at for row in rows))
    offer_blocks: list[str] = []

    for trip_history in trip_histories:
        latest = trip_history.latest
        previous_legs = trip_history.previous.legs if trip_history.previous else []
        matching_legs = [
            (index, leg)
            for index, leg in enumerate(latest.legs)
            if is_good_or_better(leg)
        ]
        if not matching_legs:
            continue

        first_leg = latest.legs[0]
        last_leg = latest.legs[-1]
        block_lines = [f"*{first_leg.data_voo} a {last_leg.data_voo}*"]

        for index, latest_leg in matching_legs:
            leg_label = "Ida" if index == 0 else "Volta" if index == 1 else f"Trecho {index + 1}"
            previous_leg = previous_legs[index] if index < len(previous_legs) else None
            status = build_leg_status(previous_leg, latest_leg)

            block_lines.append(
                f"- {leg_label}: {latest_leg.origem} -> {latest_leg.destino} ({latest_leg.data_voo})"
            )
            block_lines.append(f"  {status.summary}")
            block_lines.append(f"  📉 Preço alvo: {build_target_status(latest_leg)}")

        offer_blocks.append("\n".join(block_lines))

    if not offer_blocks:
        return "\n".join(
            [
                "*Resumo de ofertas*",
                f"Atualizado em: {latest_run}",
                "",
                "Nenhum trecho com preco bom ou excelente encontrado.",
            ]
        )

    summary_parts = [
        "*Resumo de ofertas*",
        f"Atualizado em: {latest_run}",
        f"Trechos com preco bom ou excelente: {sum(block.count('- ') for block in offer_blocks)}",
        "",
        "*Ofertas*",
        "\n\n".join(offer_blocks),
    ]
    return "\n".join(summary_parts)


def write_summary(path: Path, content: str) -> None:
    path.write_text(content + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analisa o resultado_voos.csv e resume se os precos subiram, cairam ou permaneceram iguais."
    )
    parser.add_argument("--input", type=Path, default=INPUT_CSV, help="CSV de entrada. Padrao: resultado_voos.csv")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Arquivo de resumo. Padrao: resumo_resultado.txt ou resumo_ofertas.txt com --offers-only.",
    )
    parser.add_argument(
        "--offers-only",
        action="store_true",
        help="Gera apenas o resumo_ofertas.txt com trechos de preco bom ou excelente.",
    )
    parser.add_argument(
        "--stdout-only",
        action="store_true",
        help="Mostra o resumo apenas no terminal, sem gravar arquivo.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = load_rows(args.input)
    summary = build_offers_summary(rows) if args.offers_only else build_summary(rows)
    output_path = args.output or (OUTPUT_OFFERS if args.offers_only else OUTPUT_SUMMARY)
    print(summary)
    if not args.stdout_only:
        write_summary(output_path, summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
