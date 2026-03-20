import shutil
from openpyxl import load_workbook, Workbook
from copy import copy
import os
import subprocess
from pdf2image import convert_from_path
import requests
from datetime import datetime, timedelta
from openpyxl.styles import Border, Side
import re
import xlrd

from app.core.config import settings
from app.core.create_bot import bot
from app.repositories import address_repository
from app.services.services_for_models.groups import update_groups
from app.core.database import AsyncSessionLocal


class ParsAask:
    def __init__(self):
        self.GROUP_NAMES = []

    async def download_and_generate_schedule(self, manual_url: str = None):
        today = datetime.now()
        if today.weekday() == 6:
            today += timedelta(days=1)
        i = 0
        while True:
            try:
                target_day = today + timedelta(days=i)
                day_month = int(target_day.strftime("%d%m"))
                if manual_url:
                    url = manual_url
                    manual_url = None
                else:
                    url = f"https://altask.ru/images/raspisanie/DO/{day_month}.xls"
                response = requests.get(url)
                if response.status_code != 200 and i == 0:
                    raise Exception(
                        await bot.send_message(
                            chat_id=settings.YOUR_CHAT_ID,
                            text=f"Не удалось скачать файл по ссылке: {url}",
                        )
                    )
                else:
                    file_path = f"{day_month}.xls"
                    with open(file_path, "wb") as f:
                        f.write(response.content)

                    await self.extract_group_names_from_xls(file_path)
                i += 1
                self.parse_and_generate_tables(file_path, day_month)
            except Exception:
                break

    async def extract_group_names_from_xls(self, file_path):
        group_pattern = re.compile(r"^[А-Яа-яA-Za-z]+-\d{2}$")
        group_names = set()

        workbook = xlrd.open_workbook(file_path)
        sheet = workbook.sheet_by_index(0)
        for y in range(sheet.nrows):
            for x in range(sheet.ncols):
                value = str(sheet.cell_value(y, x)).strip()
                if group_pattern.match(value):
                    group_names.add(value)

        sorted_group_names = sorted(group_names, key=lambda x: x.lower())


        self.GROUP_NAMES = list(sorted_group_names)

        async with AsyncSessionLocal() as session:
            address = await address_repository.get_address_by_name(session, address_name="пр.Ленина 68")
            await update_groups(
                session=session, groups=self.GROUP_NAMES, address_sid=address.sid)

        return print(f"[INFO] Найдено групп: {len(self.GROUP_NAMES)} и добавлено в таблицу")

    @staticmethod
    def convert_xls_to_xlsx(input_path):
        try:
            output_dir = os.path.dirname(os.path.abspath(input_path))

            subprocess.run(
                [
                    "libreoffice",
                    "--headless",
                    "--convert-to",
                    "xlsx",
                    "--outdir",
                    output_dir,
                    input_path,
                ],
                check=True,
            )
            return True
        except subprocess.CalledProcessError as e:
            print(f"[!] Ошибка конвертации: {e}")
            return False

    def read_xls_file(self, file_path):
        result = []
        try:
            workbook = xlrd.open_workbook(file_path)
            sheet = workbook.sheet_by_index(0)

            for y in range(sheet.nrows):
                for x in range(sheet.ncols):
                    value = sheet.cell_value(y, x)
                    if value in self.GROUP_NAMES:
                        ly = y + 1
                        # изза субботы снизу ебанутой до 40 клеток вниз уходит, пока поставил ограничение 13
                        while (
                            ly - y < 13
                            and ly < sheet.nrows
                            and sheet.cell_value(ly, x) not in self.GROUP_NAMES
                        ):
                            ly += 1
                        if ly >= sheet.nrows:
                            ly = sheet.nrows - 1
                        result.append({"group": value, "x": x, "y1": y + 1, "y2": ly})
            return result
        except Exception as e:
            print(f"[!] Ошибка чтения .xls: {e}")
            return None

    @staticmethod
    def create_group_sheets_single_column(groups, source_sheet, output_dir):
        os.makedirs(output_dir, exist_ok=True)

        for group in groups:
            x = group["x"] + 1
            y1 = group["y1"]
            y2 = group["y2"]
            name = group["group"]

            wb = Workbook()
            ws = wb.active
            ws.title = name
            for row in range(y1, y2 + 1):
                src_cell = source_sheet.cell(row=row, column=x)
                tgt_cell = ws.cell(row=row - y1 + 1, column=4, value=src_cell.value)

                if src_cell.has_style:
                    tgt_cell.font = copy(src_cell.font)
                    current_border = src_cell.border
                    mixed_border = Border(
                        left=Side(style="medium"),
                        right=Side(style="medium"),
                        # TODO
                        top=(
                            current_border.top
                            if current_border.top
                            else Side(style="thin", color="505050")
                        ),
                        bottom=(
                            current_border.bottom
                            if current_border.bottom
                            else Side(style="thin", color="505050")
                        ),
                    )
                    tgt_cell.border = mixed_border
                    tgt_cell.fill = copy(src_cell.fill)
                    tgt_cell.number_format = copy(src_cell.number_format)
                    tgt_cell.protection = copy(src_cell.protection)
                    tgt_cell.alignment = copy(src_cell.alignment)

            col_letter_src = source_sheet.cell(row=y1, column=x).column_letter
            ws.column_dimensions["D"].width = max(
                source_sheet.column_dimensions[col_letter_src].width, 33, 22
            )

            for row in range(y1, y2 + 1):
                if source_sheet.row_dimensions[row].height is not None:
                    ws.row_dimensions[row - y1 + 1].height = (
                        source_sheet.row_dimensions[row].height
                    )

            xlsx_path = os.path.join(output_dir, f"{name}.xlsx")
            wb.save(xlsx_path)

            try:
                subprocess.run(
                    [
                        "libreoffice",
                        "--headless",
                        "--convert-to",
                        "pdf",
                        "--outdir",
                        output_dir,
                        xlsx_path,
                    ],
                    check=True,
                )
                pdf_path = os.path.join(output_dir, f"{name}.pdf")

                images = convert_from_path(pdf_path, dpi=300)

                # TODO tut obrezat

                if images:
                    img = images[0]
                    width, height = img.size

                    crop_top = int(height * 0.00)  # обрезать % сверху
                    crop_bottom = int(height * 0.10)  # обрезать % снизу
                    crop_left = int(width * 0.15)  # обрезать % слева
                    crop_right = int(width * 0.15)  # обрезать % справа

                    cropped = img.crop(
                        (crop_left, crop_top, width - crop_right, height - crop_bottom)
                    )
                    cropped.save(os.path.join(output_dir, f"{name}.png"), "PNG")
                os.remove(xlsx_path)
                os.remove(pdf_path)

            except Exception as e:
                print(f"[!] Ошибка при конвертации файлов для группы {name}: {e}")
                continue

        print(f"группы сохранены в {output_dir}")

    def parse_and_generate_tables(self, INPUT_XLS, day_month):
        output_dir = f"./app/grop_photo/ААСК/пр.Ленина 68/{day_month}"
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
        self.convert_xls_to_xlsx(INPUT_XLS)
        groups = self.read_xls_file(INPUT_XLS)
        workbook = load_workbook(f"{INPUT_XLS}x")
        sheet = workbook.active
        self.create_group_sheets_single_column(groups, sheet, output_dir)
        if os.path.exists(INPUT_XLS):
            os.remove(INPUT_XLS)
            print(f"[INFO] Удален исходный файл: {INPUT_XLS}")
        if os.path.exists(f"{INPUT_XLS}x"):
            os.remove(f"{INPUT_XLS}x")
        return True


parse_aask = ParsAask()
