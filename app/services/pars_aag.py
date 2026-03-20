import asyncio
import re
import os
from pathlib import Path
from datetime import datetime, timedelta

import requests
import pdfplumber
from lxml import html
from PIL import Image, ImageDraw, ImageFont

from app.core.database import AsyncSessionLocal
from app.repositories import address_repository
from app.services.services_for_models.groups import update_groups


class AAGParser:
    def __init__(self):
        self.SITES = {
            "ул.Юрина 170": "https://altag.ru/student/schedule/rescheduling-1",
            "ул.Юрина 203": "https://altag.ru/student/schedule/rescheduling-2",
            "ул.Германа Титова 8": "https://altag.ru/student/schedule/rescheduling-3",
        }

        self.GROUP_REGEX = re.compile(r"[А-ЯA-ZА-яЁё]{1,3}[-–]?\d{2,4}")

        self.BASE_DIR = Path(__file__).resolve().parents[3]
        self.ROOT_SAVE_DIR = self.BASE_DIR / "app" / "grop_photo" / "ААГ"

        self.TODAY = datetime.today()

    def get_pdf_links(self, page_url, session):
        response = session.get(page_url, timeout=(5, 30))
        response.raise_for_status()

        tree = html.fromstring(response.content)
        links = tree.xpath("//a[contains(@href, '.pdf')]")

        valid_dates = []
        current_date = self.TODAY

        check_days = []
        d = current_date
        while len(check_days) < 5:
            if d.weekday() != 6:  # 6 = воскресенье
                check_days.append(d.day)
            d += timedelta(days=1)

        for link in links:
            text = link.text_content().strip()
            if text.isdigit():
                day = int(text)
                if day in check_days:
                    valid_dates.append((link.get("href"), day))

        return valid_dates

    def parse_pdf_once(self, pdf_path):
        schedules = {}

        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                if not tables:
                    continue

                for table in tables:
                    rows = len(table)
                    cols = len(table[0])

                    for col in range(cols):
                        for row in range(rows):
                            cell = table[row][col]

                            if cell and self.GROUP_REGEX.fullmatch(cell.strip()):
                                group = cell.strip().replace("–", "-")
                                result = []

                                subject_col = col
                                cabinet_col = col + 1

                                r = row + 1
                                while r < rows:
                                    subj = table[r][subject_col]

                                    if subj and self.GROUP_REGEX.fullmatch(
                                        subj.strip()
                                    ):
                                        break

                                    pair = table[r][0] if 0 < len(table[r]) else ""
                                    cabinet = (
                                        table[r][cabinet_col]
                                        if cabinet_col < len(table[r])
                                        else ""
                                    )

                                    if subj and subj.strip():
                                        result.append(
                                            [
                                                pair.strip(),
                                                subj.strip(),
                                                cabinet.strip() if cabinet else "",
                                            ]
                                        )

                                    r += 1

                                schedules[group] = result

        return schedules

    def render_image(self, data, group_name, output_path):
        margin = 30
        row_height = 80
        header_height = 70

        col_widths = [100, 450, 100]
        width = sum(col_widths) + margin * 2
        height = header_height + row_height * len(data) + margin * 2

        img = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 24)
            font_bold = ImageFont.truetype("DejaVuSans-Bold.ttf", 26)
        except Exception:
            font = font_bold = ImageFont.load_default()

        def draw_cell(x, y, w, h):
            draw.rectangle([x, y, x + w, y + h], outline="black", width=2)

        def draw_text(x, y, w, h, text, font_obj):
            lines = text.split("\n")
            line_height = font_obj.getbbox("Ay")[3]
            total_h = line_height * len(lines)
            start_y = y + (h - total_h) // 2

            for i, line in enumerate(lines):
                text_w = draw.textlength(line, font=font_obj)
                draw.text(
                    (x + (w - text_w) // 2, start_y + i * line_height),
                    line,
                    font=font_obj,
                    fill="black",
                )

        x = margin
        y = margin
        headers = ["Пара", group_name, "Каб"]

        for w, header in zip(col_widths, headers):
            draw_cell(x, y, w, header_height)
            draw_text(x, y, w, header_height, header, font_bold)
            x += w

        y += header_height

        for pair, subject, cabinet in data:
            x = margin
            for w, text in zip(col_widths, [pair, subject, cabinet]):
                draw_cell(x, y, w, row_height)
                draw_text(x, y, w, row_height, text, font)
                x += w
            y += row_height

        img.save(output_path)

    async def run(self):
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0"})
        # todo запрос на получение всех адресов с названиями из addresses
        async with AsyncSessionLocal() as session_db:
            address_objects = await address_repository.get_address_by_college(
                session_db, college_name="ААГ"
            )
            name_address_map = {
                address.name: address.sid for address in address_objects
            }
            for site_folder, url in self.SITES.items():

                pdf_links = self.get_pdf_links(url, session)
                if not pdf_links:
                    print("Нет PDF на ближайшие 5 дней")
                    continue

                for pdf_url, day in pdf_links:
                    print(f"[INFO] Обработка {pdf_url}")

                    target_date = self.TODAY.replace(day=day)
                    if day < self.TODAY.day:
                        target_date = target_date + timedelta(days=30)

                    day_month = f"{target_date.day}{target_date.month:02d}"

                    save_dir = self.ROOT_SAVE_DIR / site_folder / day_month
                    save_dir.mkdir(parents=True, exist_ok=True)

                    file_name = pdf_url.split("/")[-1]
                    response = session.get(pdf_url, timeout=(5, 60))

                    with open(file_name, "wb") as f:
                        f.write(response.content)

                    schedules = self.parse_pdf_once(file_name)
                    GROUP_NAMES = list(schedules)

                    await update_groups(
                        session=session_db,
                        groups=GROUP_NAMES,
                        address_sid=name_address_map.get(site_folder),
                    )
                    await session_db.commit()

                    print(f"[INFO] Найдено групп: {len(schedules)}")

                    for group, schedule in schedules.items():
                        if schedule:
                            self.render_image(
                                schedule, group, save_dir / f"{group}.png"
                            )

                    os.remove(file_name)


parse_aag = AAGParser()

if __name__ == "__main__":
    asyncio.run(AAGParser().run())
