"""Tworzy zbiorczy raport Excel ze wszystkich batchow."""

import pandas as pd
import json
from pathlib import Path

output_dir = Path('test_cycles')

# Zbierz wszystkie metryki
all_metrics = []
for batch_num in [1, 2, 3]:
    metrics_file = list(output_dir.glob(f'batch_{batch_num}_metrics.json'))
    if metrics_file:
        with open(metrics_file[0], 'r') as f:
            m = json.load(f)
            all_metrics.append(m)

# Tworz Summary sheet
summary_data = []
for m in all_metrics:
    batch = m['batch_name']
    v1 = m['v1']
    v2 = m['v2']
    summary_data.append({
        'Batch': batch,
        'V1_Contact_TP': int(v1['contact_tp']),
        'V1_Contact_FP': int(v1['contact_fp']),
        'V1_Contact_FN': int(v1['contact_fn']),
        'V1_Precision': v1['contact_precision'],
        'V1_Recall': v1['contact_recall'],
        'V2_Contact_TP': int(v2['contact_tp']),
        'V2_Contact_FP': int(v2['contact_fp']),
        'V2_Contact_FN': int(v2['contact_fn']),
        'V2_Precision': v2['contact_precision'],
        'V2_Recall': v2['contact_recall'],
        'V1_Account_TP': int(v1['account_tp']),
        'V1_Account_FP': int(v1['account_fp']),
        'V1_Account_FN': int(v1['account_fn']),
        'V2_Account_TP': int(v2['account_tp']),
        'V2_Account_FP': int(v2['account_fp']),
        'V2_Account_FN': int(v2['account_fn']),
    })

# Dodaj wiersz z sumami
totals = {
    'Batch': 'TOTAL',
    'V1_Contact_TP': sum(d['V1_Contact_TP'] for d in summary_data),
    'V1_Contact_FP': sum(d['V1_Contact_FP'] for d in summary_data),
    'V1_Contact_FN': sum(d['V1_Contact_FN'] for d in summary_data),
    'V2_Contact_TP': sum(d['V2_Contact_TP'] for d in summary_data),
    'V2_Contact_FP': sum(d['V2_Contact_FP'] for d in summary_data),
    'V2_Contact_FN': sum(d['V2_Contact_FN'] for d in summary_data),
    'V1_Account_TP': sum(d['V1_Account_TP'] for d in summary_data),
    'V1_Account_FP': sum(d['V1_Account_FP'] for d in summary_data),
    'V1_Account_FN': sum(d['V1_Account_FN'] for d in summary_data),
    'V2_Account_TP': sum(d['V2_Account_TP'] for d in summary_data),
    'V2_Account_FP': sum(d['V2_Account_FP'] for d in summary_data),
    'V2_Account_FN': sum(d['V2_Account_FN'] for d in summary_data),
}
totals['V1_Precision'] = totals['V1_Contact_TP'] / (totals['V1_Contact_TP'] + totals['V1_Contact_FP']) if (totals['V1_Contact_TP'] + totals['V1_Contact_FP']) > 0 else 0
totals['V1_Recall'] = totals['V1_Contact_TP'] / (totals['V1_Contact_TP'] + totals['V1_Contact_FN']) if (totals['V1_Contact_TP'] + totals['V1_Contact_FN']) > 0 else 0
totals['V2_Precision'] = totals['V2_Contact_TP'] / (totals['V2_Contact_TP'] + totals['V2_Contact_FP']) if (totals['V2_Contact_TP'] + totals['V2_Contact_FP']) > 0 else 0
totals['V2_Recall'] = totals['V2_Contact_TP'] / (totals['V2_Contact_TP'] + totals['V2_Contact_FN']) if (totals['V2_Contact_TP'] + totals['V2_Contact_FN']) > 0 else 0
summary_data.append(totals)

df_summary = pd.DataFrame(summary_data)

# Wczytaj wszystkie wyniki detailowe
all_v1 = []
all_v2 = []
for batch_num in [1, 2, 3]:
    v1_files = sorted(output_dir.glob(f'batch_{batch_num}_structural_*.xlsx'))
    v2_files = sorted(output_dir.glob(f'batch_{batch_num}_raw_text_*.xlsx'))
    if v1_files:
        df = pd.read_excel(v1_files[-1])  # Ostatni (najnowszy)
        all_v1.append(df)
    if v2_files:
        df = pd.read_excel(v2_files[-1])
        all_v2.append(df)

df_all_v1 = pd.concat(all_v1, ignore_index=True) if all_v1 else pd.DataFrame()
df_all_v2 = pd.concat(all_v2, ignore_index=True) if all_v2 else pd.DataFrame()

# Zapisz do Excel
output_file = 'test_cycles/ALL_RESULTS_COMBINED.xlsx'
with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
    df_summary.to_excel(writer, sheet_name='Summary', index=False)
    if not df_all_v1.empty:
        df_all_v1.to_excel(writer, sheet_name='V1_Structural', index=False)
    if not df_all_v2.empty:
        df_all_v2.to_excel(writer, sheet_name='V2_RawText', index=False)

print(f'Zapisano: {output_file}')
print(f'V1 rekordow: {len(df_all_v1)}')
print(f'V2 rekordow: {len(df_all_v2)}')
print()
print('=== PODSUMOWANIE KONCOWE ===')
print(f"V1 Precision: {totals['V1_Precision']:.1%}")
print(f"V1 Recall: {totals['V1_Recall']:.1%}")
print(f"V2 Precision: {totals['V2_Precision']:.1%}")
print(f"V2 Recall: {totals['V2_Recall']:.1%}")
