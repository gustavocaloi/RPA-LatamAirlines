from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


LATAM_URL = "https://www.latamairlines.com/br/pt"
ROOT_DIR = Path(__file__).resolve().parent.parent
INPUT_CSV = Path(os.getenv("INPUT_CSV", ROOT_DIR / "voos.csv"))
OUTPUT_CSV = Path(os.getenv("OUTPUT_CSV", ROOT_DIR / "resultado_voos.csv"))
PROFILE_DIR = Path(os.getenv("PROFILE_DIR", ROOT_DIR / ".playwright-profile"))
DEFAULT_BROWSER_CHANNEL = os.getenv("PLAYWRIGHT_BROWSER_CHANNEL", "chrome").strip() or None
DEFAULT_PRECO_ALVO_EXCELENTE = "230"
DEFAULT_PRECO_ALVO_BOM = "260"
DEFAULT_PRECO_ALVO_EVITAR = "400"
ORIGIN_FIELD_SELECTOR = "[data-testid='fsb-origin--text-field']"
DESTINATION_FIELD_SELECTOR = "[data-testid='fsb-destination--text-field']"
RETRYABLE_NAVIGATION_ERRORS = (
    "ERR_HTTP2_PROTOCOL_ERROR",
    "ERR_NETWORK_CHANGED",
    "ERR_CONNECTION_CLOSED",
    "ERR_CONNECTION_RESET",
    "ERR_TIMED_OUT",
)
DEFAULT_SEARCH_PAUSE_SECONDS = 3.0


@dataclass
class FlightRow:
    origem: str
    destino: str
    data_ida: str
    data_volta: str
    preco_alvo_excelente: str
    preco_alvo_bom: str
    preco_alvo_evitar: str


@dataclass
class FlightResultRow:
    codigo_consulta: str
    data_hora_processamento: str
    origem: str
    destino: str
    data_voo: str
    menor_preco: str
    preco_alvo_excelente: str
    preco_alvo_bom: str
    preco_alvo_evitar: str


class LatamDateNotFoundError(RuntimeError):
    pass


class LatamFareNotFoundError(RuntimeError):
    pass


def log(message: str) -> None:
    print(f"[latam] {message}")


def processing_timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")


def processing_date() -> datetime.date:
    return datetime.now().astimezone().date()


def parse_processing_timestamp(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S %z")


def env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        return float(raw_value.replace(",", "."))
    except ValueError:
        log(f"Valor invalido para {name}: {raw_value!r}. Usando {default:g}s.")
        return default


def consultation_code(processed_at: str, sequence: int) -> str:
    base = parse_processing_timestamp(processed_at).strftime("%Y%m%d%H%M%S")
    return f"CONS-{base}-{sequence:04d}"


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


def wait_for_searchbox(page: Page) -> None:
    page.locator(ORIGIN_FIELD_SELECTOR).first.wait_for(state="visible", timeout=30_000)
    page.locator(DESTINATION_FIELD_SELECTOR).first.wait_for(state="visible", timeout=30_000)


def is_retryable_navigation_error(exc: PlaywrightError) -> bool:
    message = str(exc)
    return any(error_code in message for error_code in RETRYABLE_NAVIGATION_ERRORS)


def stop_pending_navigation(page: Page) -> None:
    try:
        page.evaluate("window.stop()")
    except PlaywrightError:
        pass


def reset_page_after_navigation_error(page: Page) -> None:
    stop_pending_navigation(page)
    try:
        page.goto("about:blank", wait_until="domcontentloaded", timeout=5_000)
    except PlaywrightError:
        pass


def goto_latam_home(page: Page) -> None:
    last_error: PlaywrightError | None = None
    for attempt in range(1, 4):
        try:
            page.goto(LATAM_URL, wait_until="domcontentloaded", timeout=60_000)
            return
        except PlaywrightError as exc:
            if not is_retryable_navigation_error(exc):
                raise
            last_error = exc
            if attempt == 3:
                break
            log(f"Falha temporaria ao abrir LATAM ({attempt}/3); tentando novamente.")
            reset_page_after_navigation_error(page)
            page.wait_for_timeout(2_000 * attempt)

    if last_error:
        raise last_error


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
                preco_alvo_excelente=row.get("preco_alvo_excelente", DEFAULT_PRECO_ALVO_EXCELENTE).strip(),
                preco_alvo_bom=row.get("preco_alvo_bom", DEFAULT_PRECO_ALVO_BOM).strip(),
                preco_alvo_evitar=row.get("preco_alvo_evitar", DEFAULT_PRECO_ALVO_EVITAR).strip(),
            )
            for row in reader
        ]


def is_row_processable(row: FlightRow, today: datetime.date) -> bool:
    departure_date = parse_date(row.data_ida).date()
    return_date = parse_date(row.data_volta).date()
    return departure_date >= today and return_date >= today


def filter_processable_rows(rows: list[FlightRow], today: datetime.date) -> list[FlightRow]:
    valid_rows: list[FlightRow] = []
    for row in rows:
        if is_row_processable(row, today):
            valid_rows.append(row)
            continue

        log(
            "Ignorando rota "
            f"{row.origem}->{row.destino} "
            f"({row.data_ida} / {row.data_volta}) porque a data do voo ja passou."
        )
    return valid_rows


def pick_airport(page: Page, selector: str, airport_code: str) -> None:
    field = page.locator(selector).first
    field.wait_for(state="visible", timeout=30_000)
    field.scroll_into_view_if_needed(timeout=5_000)
    try:
        field.click(timeout=10_000)
    except PlaywrightTimeoutError:
        dismiss_login_banner(page)
        field.click(force=True, timeout=10_000)
    field.fill(airport_code, timeout=10_000)
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
    for attempt in range(1, 3):
        try:
            goto_latam_home(page)
            page.wait_for_timeout(4_000)
            dismiss_login_banner(page)
            wait_for_searchbox(page)

            log(f"Preenchendo rota {row.origem} -> {row.destino}")
            pick_airport(page, ORIGIN_FIELD_SELECTOR, row.origem)
            page.keyboard.press("Escape")
            pick_airport(page, DESTINATION_FIELD_SELECTOR, row.destino)

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
                raise LatamDateNotFoundError(f"Data de ida {row.data_ida} nao apareceu no calendario da LATAM.")
            departure_button.click(force=True, no_wait_after=True)
            page.wait_for_timeout(700)

            return_button = page.locator(f"[data-testid='date-{return_date:%Y-%m-%d}']")
            if not return_button.count():
                raise LatamDateNotFoundError(f"Data de volta {row.data_volta} nao apareceu no calendario da LATAM.")
            return_button.click(force=True, no_wait_after=True)
            page.wait_for_timeout(1_000)
            return
        except (PlaywrightTimeoutError, PlaywrightError):
            if attempt == 2:
                raise
            log("Campo de busca da LATAM demorou para responder; recarregando e tentando a rota novamente.")
            reset_page_after_navigation_error(page)
            page.wait_for_timeout(3_000)


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
                    fare = detail.get("fare")
                    if not isinstance(fare, dict) or not fare.get("amount"):
                        raise LatamFareNotFoundError(
                            f"Tarifa {direction} indisponivel para {target_date_str}."
                        )
                    return float(fare["amount"])

    raise LatamFareNotFoundError(f"Nao encontrei tarifa {direction} para {target_date_str}.")


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


def build_leg_rows(playwright: Any, row: FlightRow, processed_at: str, codigo_consulta: str) -> list[FlightResultRow]:
    departure_date = parse_date(row.data_ida)
    return_date = parse_date(row.data_volta)

    outbound_price = estimate_one_way_price(playwright, row.origem, row.destino, departure_date)
    inbound_price = estimate_one_way_price(playwright, row.destino, row.origem, return_date)

    log(f"Menor preco estimado ida {row.origem}->{row.destino} em {row.data_ida}: BRL {outbound_price:.2f}")
    log(f"Menor preco estimado volta {row.destino}->{row.origem} em {row.data_volta}: BRL {inbound_price:.2f}")

    return [
        FlightResultRow(
            codigo_consulta=codigo_consulta,
            data_hora_processamento=processed_at,
            origem=row.origem,
            destino=row.destino,
            data_voo=row.data_ida,
            menor_preco=f"{outbound_price:.2f}",
            preco_alvo_excelente=row.preco_alvo_excelente,
            preco_alvo_bom=row.preco_alvo_bom,
            preco_alvo_evitar=row.preco_alvo_evitar,
        ),
        FlightResultRow(
            codigo_consulta=codigo_consulta,
            data_hora_processamento=processed_at,
            origem=row.destino,
            destino=row.origem,
            data_voo=row.data_volta,
            menor_preco=f"{inbound_price:.2f}",
            preco_alvo_excelente=row.preco_alvo_excelente,
            preco_alvo_bom=row.preco_alvo_bom,
            preco_alvo_evitar=row.preco_alvo_evitar,
        ),
    ]


BASE_RESULT_FIELDNAMES = ["codigo_consulta", "data_hora_processamento", "origem", "destino", "data_voo", "menor_preco"]
PRECO_ALVO_FIELDNAMES = ["preco_alvo_excelente", "preco_alvo_bom", "preco_alvo_evitar"]
RESULT_FIELDNAMES = BASE_RESULT_FIELDNAMES + PRECO_ALVO_FIELDNAMES

LEGACY_RESULT_FIELDNAMES = ["data_hora_processamento", "origem", "destino", "data_voo", "menor_preco"]


def migrate_results(output_path: Path) -> None:
    with output_path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        legacy_rows = list(reader)

    migrated_rows: list[dict[str, str]] = []
    counters_by_timestamp: dict[str, int] = {}
    position_by_timestamp: dict[str, int] = {}

    for row in legacy_rows:
        processed_at = row["data_hora_processamento"]
        position = position_by_timestamp.get(processed_at, 0)

        if position % 2 == 0:
            counters_by_timestamp[processed_at] = counters_by_timestamp.get(processed_at, 0) + 1

        codigo_consulta = row.get("codigo_consulta") or consultation_code(processed_at, counters_by_timestamp[processed_at])
        position_by_timestamp[processed_at] = position + 1

        migrated_rows.append(
            {
                "codigo_consulta": codigo_consulta,
                "data_hora_processamento": processed_at,
                "origem": row["origem"],
                "destino": row["destino"],
                "data_voo": row["data_voo"],
                "menor_preco": row["menor_preco"],
                "preco_alvo_excelente": row.get("preco_alvo_excelente", DEFAULT_PRECO_ALVO_EXCELENTE),
                "preco_alvo_bom": row.get("preco_alvo_bom", DEFAULT_PRECO_ALVO_BOM),
                "preco_alvo_evitar": row.get("preco_alvo_evitar", DEFAULT_PRECO_ALVO_EVITAR),
            }
        )

    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=RESULT_FIELDNAMES)
        writer.writeheader()
        writer.writerows(migrated_rows)


def ensure_results_file(output_path: Path) -> None:
    if output_path.exists() and output_path.stat().st_size > 0:
        with output_path.open(newline="", encoding="utf-8") as file:
            reader = csv.reader(file)
            existing_header = next(reader, [])

        if existing_header == RESULT_FIELDNAMES:
            return

        if existing_header in (LEGACY_RESULT_FIELDNAMES, BASE_RESULT_FIELDNAMES):
            migrate_results(output_path)
            return

        raise RuntimeError(
            "Formato inesperado em resultado_voos.csv. "
            f"Cabecalho encontrado: {existing_header}"
        )

    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=RESULT_FIELDNAMES)
        writer.writeheader()


def append_results(output_path: Path, rows: list[FlightResultRow]) -> None:
    with output_path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=RESULT_FIELDNAMES)
        writer.writerows([row.__dict__ for row in rows])
        file.flush()


def run(
    input_csv: Path,
    output_csv: Path,
    profile_dir: Path,
    headless: bool,
    browser_channel: str | None,
    use_home_searchbox: bool,
) -> None:
    rows = filter_processable_rows(load_rows(input_csv), processing_date())
    processed_at = processing_timestamp()
    ensure_results_file(output_csv)

    if not rows:
        log("Nenhuma rota futura para processar.")
        return

    with sync_playwright() as playwright:
        context = None
        page = None
        if use_home_searchbox:
            profile_dir.mkdir(exist_ok=True, parents=True)
            launch_options = dict(
                user_data_dir=str(profile_dir),
                headless=headless,
                ignore_default_args=["--enable-automation"],
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
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
            if browser_channel:
                launch_options["channel"] = browser_channel

            context = playwright.chromium.launch_persistent_context(**launch_options)
            context.add_init_script(
                """
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR', 'pt', 'en-US', 'en'] });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4] });
                """
            )

            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(15_000)

        search_pause_seconds = max(0.0, env_float("LATAM_SEARCH_PAUSE_SECONDS", DEFAULT_SEARCH_PAUSE_SECONDS))

        try:
            for index, row in enumerate(rows, start=1):
                codigo_consulta = consultation_code(processed_at, index)
                try:
                    if page:
                        open_site_and_fill_searchbox(page, row)
                    leg_rows = build_leg_rows(playwright, row, processed_at, codigo_consulta)
                    append_results(output_csv, leg_rows)
                    log(f"Resultado parcial gravado em {output_csv.name}")
                except LatamDateNotFoundError as exc:
                    log(f"{exc} Ignorando esta rota e seguindo para a proxima data.")
                    continue
                except LatamFareNotFoundError as exc:
                    log(f"{exc} Ignorando esta rota e seguindo para a proxima data.")
                    continue
                except PlaywrightTimeoutError as exc:
                    log(f"Timeout ao preencher a rota {row.origem}->{row.destino}: {exc}. Ignorando esta rota e seguindo.")
                    continue
                except PlaywrightError as exc:
                    log(f"Erro do navegador ao processar a rota {row.origem}->{row.destino}: {exc}. Ignorando esta rota e seguindo.")
                    continue
                finally:
                    if index < len(rows) and search_pause_seconds > 0:
                        log(f"Aguardando {search_pause_seconds:g}s antes da proxima pesquisa.")
                        if page:
                            page.wait_for_timeout(int(search_pause_seconds * 1000))
                        else:
                            time.sleep(search_pause_seconds)
        finally:
            if context:
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
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=PROFILE_DIR,
        help="Diretorio do perfil persistente do navegador.",
    )
    parser.add_argument(
        "--browser-channel",
        default=DEFAULT_BROWSER_CHANNEL,
        help="Canal do navegador Playwright. Use vazio para o Chromium embutido do container.",
    )
    parser.add_argument(
        "--use-home-searchbox",
        action="store_true",
        help="Abre a home da LATAM e preenche o buscador antes de consultar o calendario.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        browser_channel = args.browser_channel.strip() if isinstance(args.browser_channel, str) else args.browser_channel
        run(
            args.input,
            args.output,
            args.profile_dir,
            headless=not args.headed,
            browser_channel=browser_channel or None,
            use_home_searchbox=args.use_home_searchbox,
        )
        return 0
    except Exception as exc:
        log(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
