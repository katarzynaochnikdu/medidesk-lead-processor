"""
Test chaotic data - 10 firm, zapis przyrostowy.
"""
import asyncio
import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from company_intel.orchestrator import CompanyIntelOrchestrator

OUTPUT_FILE = "test_chaotic_10_results.json"

def load_test_cases(start_row=149, count=10):
    """Load test cases from Excel."""
    df = pd.read_excel('companies_data_reference.xlsx')
    test_data = df.iloc[start_row:start_row + count]
    
    cases = []
    for idx, row in test_data.iterrows():
        input_name = row['Nazwa testowana']
        expected_nip = str(row['NIP']).strip() if pd.notna(row['NIP']) else None
        
        if not input_name or pd.isna(input_name):
            continue
            
        if expected_nip:
            expected_nip = ''.join(c for c in expected_nip if c.isdigit())
            if len(expected_nip) != 10:
                expected_nip = None
        
        cases.append({
            'input': str(input_name).strip(),
            'expected_nip': expected_nip,
            'row_number': idx + 1,
        })
    
    return cases


def save_results(results, summary):
    """Save results incrementally."""
    data = {
        'timestamp': datetime.now().isoformat(),
        'summary': summary,
        'results': results,
    }
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[SAVED] {OUTPUT_FILE}")


async def main():
    print("=" * 60)
    print("TEST: Chaotic Data - 10 firm (zapis przyrostowy)")
    print("=" * 60)
    
    test_cases = load_test_cases(start_row=149, count=10)
    print(f"Loaded {len(test_cases)} test cases")
    
    orchestrator = CompanyIntelOrchestrator()
    
    results = []
    success_count = 0
    fail_count = 0
    
    for i, test_case in enumerate(test_cases, 1):
        input_text = test_case['input']
        expected_nip = test_case['expected_nip']
        row_num = test_case['row_number']
        
        print(f"\n[{i}/{len(test_cases)}] Row {row_num}: '{input_text[:50]}...'")
        print(f"    Expected: {expected_nip or 'N/A'}")
        
        try:
            result = await orchestrator.analyze_chaotic(input_text)
            
            found_nip = None
            strategy = None
            confidence = 0
            
            if result and result.get('nip_data'):
                nip_data = result['nip_data']
                if nip_data.get('found') and nip_data.get('nip'):
                    found_nip = nip_data['nip']
                    strategy = nip_data.get('strategy_used')
                    confidence = nip_data.get('confidence', 0)
            
            is_success = (found_nip == expected_nip) if expected_nip else (not found_nip)
            
            if is_success:
                success_count += 1
                print(f"    Found: {found_nip} -> OK")
            else:
                fail_count += 1
                print(f"    Found: {found_nip} -> FAIL")
            
            results.append({
                'row': row_num,
                'input': input_text,
                'expected': expected_nip,
                'found': found_nip,
                'ok': is_success,
                'strategy': strategy,
                'confidence': confidence,
            })
            
        except Exception as e:
            fail_count += 1
            print(f"    ERROR: {e}")
            results.append({
                'row': row_num,
                'input': input_text,
                'expected': expected_nip,
                'found': None,
                'ok': False,
                'error': str(e),
            })
        
        # Zapis przyrostowy po kazdej firmie
        summary = {
            'total': len(results),
            'success': success_count,
            'fail': fail_count,
            'rate': f"{success_count/len(results)*100:.1f}%" if results else "0%",
        }
        save_results(results, summary)
    
    # Podsumowanie
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    rate = (success_count / len(results) * 100) if results else 0
    print(f"Total: {len(results)}")
    print(f"Success: {success_count} ({rate:.1f}%)")
    print(f"Fail: {fail_count}")
    
    # Lista nieudanych
    failed = [r for r in results if not r['ok']]
    if failed:
        print("\nFailed:")
        for r in failed:
            print(f"  Row {r['row']}: expected={r['expected']}, found={r['found']}")
    
    await orchestrator.close()
    return rate


if __name__ == "__main__":
    asyncio.run(main())
