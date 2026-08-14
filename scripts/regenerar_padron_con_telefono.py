"""Regenera data/padron.csv agregando el celular de cada socio (para /admin/nueva)."""
import csv
import re
import sys
import openpyxl

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ORIGEN = r"D:\solicitudes- ficha de inscripcion\PADRON general junio 2026.xlsx"
DESTINO = r"D:\whatsapp-agentkit\data\padron.csv"

wb = openpyxl.load_workbook(ORIGEN, read_only=True, data_only=True)
ws = wb.active

filas_out = []
total = 0
con_celular = 0

encabezado = None
for i, row in enumerate(ws.iter_rows(values_only=True)):
    if i == 0:
        encabezado = {nombre: idx for idx, nombre in enumerate(row)}
        continue
    total += 1
    dni = (row[encabezado["dni"]] or "")
    dni = re.sub(r"\D", "", str(dni))
    if not dni:
        continue
    celular = (row[encabezado["celular"]] or "")
    celular = re.sub(r"\D", "", str(celular))
    if celular:
        con_celular += 1
    filas_out.append({
        "dni": dni,
        "apellido_paterno": (row[encabezado["ape_pat"]] or "").strip() if row[encabezado["ape_pat"]] else "",
        "apellido_materno": (row[encabezado["ape_mat"]] or "").strip() if row[encabezado["ape_mat"]] else "",
        "nombres": (row[encabezado["nombres"]] or "").strip() if row[encabezado["nombres"]] else "",
        "codigo": str(row[encabezado["codigo"]] or "").strip(),
        "tipo_socio": (row[encabezado["tipsoc"]] or "").strip() if row[encabezado["tipsoc"]] else "",
        "celular": celular,
    })

with open(DESTINO, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=[
        "dni", "apellido_paterno", "apellido_materno", "nombres", "codigo", "tipo_socio", "celular"
    ])
    writer.writeheader()
    writer.writerows(filas_out)

print(f"Filas procesadas: {total}")
print(f"Filas escritas: {len(filas_out)}")
print(f"Con celular: {con_celular}")
print(f"Guardado en: {DESTINO}")
