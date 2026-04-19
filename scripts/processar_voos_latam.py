from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


LATAM_URL = "https://www.latamairlines.com/br/pt"
ROOT_DIR = Path(__file__).resolve().parent.parent
INPUT_CSV = ROOT_DIR / "voos.csv"
OUTPUT_CSV = ROOT_DIR / "resultado_voos.csv"
PROFILE_DIR = ROOT_DIR / ".playwright-profile"


@dataclass
class FlightRow:
    origem: str
    destino: str
    data_ida: str
    data_volta: str


@dataclass
class FlightResultRow:
    data_hora_processamento: str
    origem: str
    destino: str
    data_voo: str
    menor_preco: str


def log(message: str) -> None:
    print(f"[latam] {message}")


def processing_timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")


def first_visible(locators: list[Locator], timeout_ms: int = 2500) -> Locator | None:
    for locator in locators:
        candidate = locator.first
        try:
            candidate.wait_for(state="visible", timeout=timeout_ms)
            return candidate
        except PlaywrightTimeoutError:
            continue
    return None


def dismiss_login_banner(page: Page) -> None:
    close_button = page.locator("button[aria-label*='Fechar convite' i]")
    if close_button.count():
        close_button.first.click(force=True, no_wait_after=True)
        page.wait_for_timeout(800)


def parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%d/%m/%Y")


def month_clicks(current_month: datetime, target_month: datetime) -> int:
    return (target_month.year - current_month.year) * 12 + (target_month.month - current_month.month)


def format_month_key(value: datetime) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def parse_calendar_heading(value: str) -> datetime:
    month_str, year_str = value.split("-")
    return datetime(int(year_str), int(month_str), 1)


def calendar_headers() -> dict[str, str]:
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": "pt-BR",
        "referer": LATAM_URL,
        "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/135.0.0.0 Safari/537.36"
        ),
        "x-latam-action-name": "home-homepage-web-customer.searchbox_calendar.load",
        "x-latam-app-session-id": str(uuid4()),
        "x-latam-application-country": "br",
        "x-latam-application-lang": "pt",
        "x-latam-application-name": "xp-web-products-searchbox-lib",
        "x-latam-application-oc": "br",
        "x-latam-client-name": "xp-web-products-searchbox-lib",
        "x-latam-request-id": str(uuid4()),
        "x-latam-track-id": str(uuid4()),
    }


def load_rows(csv_path: Path) -> list[FlightRow]:
    with csv_path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        return [
            FlightRow(
                origem=row["origem"].strip().upper(),
                destino=row["destino"].strip().upper(),
                data_ida=row["data_ida"].strip(),
                data_volta=row["data_volta"].strip(),
            )
            for row in reader
        ]


def pick_airport(page: Page, selector: str, airport_code: str) -> None:
    field = page.locator(selector).first
    field.click()
    field.fill(airport_code)
    page.wait_for_timeout(1000)

    suggestion = first_visible(
        [
            page.get_by_role("option", name=re.compile(rf"\\b{re.escape(airport_code)}\\b", re.I)),
            page.get_by_role("button", name=re.compile(rf"\\b{re.escape(airport_code)}\\b", re.I)),
        ],
        timeout_ms=1500,
    )
    if suggestion:
        suggestion.click(force=True, no_wait_after=True)
    else:
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter")

    page.wait_for_timeout(1000)


def open_site_and_fill_searchbox(page: Page, row: FlightRow) -> None:
    page.goto(LATAM_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(4_000)
    dismiss_login_banner(page)

    log(f"Preenchendo rota {row.origem} -> {row.destino}")
    pick_airport(page, "[data-testid='fsb-origin--text-field']", row.origem)
    pick_airport(page, "[data-testid='fsb-destination--text-field']", row.destino)

    departure_date = parse_date(row.data_ida)
    return_date = parse_date(row.data_volta)

    page.locator("[data-testid='fsb-departure--component-wrapper']").click(force=True, no_wait_after=True)
    page.wait_for_timeout(1_000)

    current_heading = page.locator("[data-testid='fsb-calendar-desktop--calendar'] [role='heading']").first
    current_month = parse_calendar_heading(current_heading.get_attribute("data-testid"))
    for _ in range(month_clicks(current_month, departure_date.replace(day=1))):
        page.locator("[data-testid='fsb-calendar-desktop--btn-next-month']").first.click(
            force=True,
            no_wait_after=True,
        )
        page.wait_for_timeout(500)

    departure_button = page.locator(f"[data-testid='date-{departure_date:%Y-%m-%d}']")
    if not departure_button.count():
        raise RuntimeError(f"Data de ida {row.data_ida} nao apareceu no calendario da LATAM.")
    departure_button.click(force=True, no_wait_after=True)
    page.wait_for_timeout(700)

    return_button = page.locator(f"[data-testid='date-{return_date:%Y-%m-%d}']")
    if not return_button.count():
        raise RuntimeError(f"Data de volta {row.data_volta} nao apareceu no calendario da LATAM.")
    return_button.click(force=True, no_wait_after=True)
    page.wait_for_timeout(1_000)


def fetch_calendar_month(playwright: Any, origin: str, destination: str, target_date: datetime) -> dict[str, Any]:
    month_url = (
        "https://www.latamairlines.com/bff/web-products-searchbox/v1/calendar"
        f"?origin={origin}&destination={destination}&month={target_date.month}"
        f"&year={target_date.year}&isRoundTrip=true&extended=true"
    )
    request = playwright.request.new_context(extra_http_headers=calendar_headers())
    try:
        response = request.get(month_url)
        if response.status != 200:
            raise RuntimeError(f"Calendario LATAM respondeu com status {response.status}.")
        return response.json()
    finally:
        request.dispose()


def extract_calendar_fare(calendar_payload: dict[str, Any], direction: str, target_date: datetime) -> float:
    target_date_str = f"{target_date:%Y-%m-%d}"
    target_month = format_month_key(target_date)

    for group in calendar_payload.get("days", []):
        for calendar in group.get("calendar", []):
            if calendar.get("month") != target_month:
                continue
            if calendar.get("direction") != direction:
                continue
            for detail in calendar.get("detailsCalendar", []):
                if detail.get("date") == target_date_str:
                    fare = detail.get("fare", {})
                    return float(fare["amount"])

    raise RuntimeError(f"Nao encontrei tarifa {direction} para {target_date_str}.")


def estimate_lowest_price(playwright: Any, row: FlightRow) -> float:
    departure_date = parse_date(row.data_ida)
    return_date = parse_date(row.data_volta)

    departure_calendar = fetch_calendar_month(playwright, row.origem, row.destino, departure_date)
    if format_month_key(return_date) == format_month_key(departure_date):
        return_calendar = departure_calendar
    else:
        return_calendar = fetch_calendar_month(playwright, row.origem, row.destino, return_date)

    outbound_amount = extract_calendar_fare(departure_calendar, "OUTBOUND", departure_date)
    inbound_amount = extract_calendar_fare(return_calendar, "INBOUND", return_date)
    return round(outbound_amount + inbound_amount, 2)


def estimate_one_way_price(playwright: Any, origin: str, destination: str, flight_date: datetime) -> float:
    calendar = fetch_calendar_month(playwright, origin, destination, flight_date)
    return round(extract_calendar_fare(calendar, "OUTBOUND", flight_date), 2)


def build_leg_rows(playwright: Any, row: FlightRow, processed_at: str) -> list[FlightResultRow]:
    departure_date = parse_date(row.data_ida)
    return_date = parse_date(row.data_volta)

    outbound_price = estimate_one_way_price(playwright, row.origem, row.destino, departure_date)
    inbound_price = estimate_one_way_price(playwright, row.destino, row.origem, return_date)

    log(f"Menor preco estimado ida {row.origem}->{row.destino} em {row.data_ida}: BRL {outbound_price:.2f}")
    log(f"Menor preco estimado volta {row.destino}->{row.origem} em {row.data_volta}: BRL {inbound_price:.2f}")

    return [
        FlightResultRow(
            data_hora_processamento=processed_at,
            origem=row.origem,
            destino=row.destino,
            data_voo=row.data_ida,
            menor_preco=f"{outbound_price:.2f}",
        ),
        FlightResultRow(
            data_hora_processamento=processed_at,
            origem=row.destino,
            destino=row.origem,
            data_voo=row.data_volta,
            menor_preco=f"{inbound_price:.2f}",
        ),
    ]


RESULT_FIELDNAMES = ["data_hora_processamento", "origem", "destino", "data_voo", "menor_preco"]


def ensure_results_file(output_path: Path) -> None:
    if output_path.exists() and output_path.stat().st_size > 0:
        return

    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=RESULT_FIELDNAMES)
        writer.writeheader()


def append_results(output_path: Path, rows: list[FlightResultRow]) -> None:
    with output_path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=RESULT_FIELDNAMES)
        writer.writerows([row.__dict__ for row in rows])
        file.flush()


def run(input_csv: Path, output_csv: Path, headless: bool) -> None:
    rows = load_rows(input_csv)
    PROFILE_DIR.mkdir(exist_ok=True)
    processed_at = processing_timestamp()
    ensure_results_file(output_csv)

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=headless,
            ignore_default_args=["--enable-automation"],
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ],
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            viewport={"width": 1440, "height": 960},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/135.0.0.0 Safari/537.36"
            ),
        )
        context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR', 'pt', 'en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4] });
            """
        )

        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(15_000)

        for row in rows:
            open_site_and_fill_searchbox(page, row)
            leg_rows = build_leg_rows(playwright, row, processed_at)
            append_results(output_csv, leg_rows)
            log(f"Resultado parcial gravado em {output_csv.name}")

        context.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Le o CSV de voos, preenche a busca da LATAM e grava um CSV com o menor preco estimado."
    )
    parser.add_argument("--input", type=Path, default=INPUT_CSV, help="CSV de entrada. Padrao: voos.csv")
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_CSV,
        help="CSV de saida. Padrao: resultado_voos.csv",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Abre o Chrome visivelmente durante a execucao.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        run(args.input, args.output, headless=not args.headed)
        return 0
    except Exception as exc:
        log(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
