"""
Test chaotic data processing for companies from rows 150-200 of companies_data_reference.xlsx.

Tests the CHAOTIC scenario - only company name as input, no NIP or website.
"""
import asyncio
import sys
import os
import json
from datetime import datetime

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from company_intel.orchestrator import CompanyIntelOrchestrator

# Load test data from Excel
def load_test_cases():
    """Load test cases from Excel file."""
    df = pd.read_excel('companies_data_reference.xlsx')
    
    # Extract rows 150-200 (0-indexed: 149:200)
    test_data = df.iloc[149:200]
    
    cases = []
    for idx, row in test_data.iterrows():
        # Get input name (chaotic data)
        input_name = row['Nazwa testowana']
        expected_nip = str(row['NIP']).strip() if pd.notna(row['NIP']) else None
        
        if not input_name or pd.isna(input_name):
            continue
            
        # Clean NIP (remove any non-digits)
        if expected_nip:
            expected_nip = ''.join(c for c in expected_nip if c.isdigit())
            if len(expected_nip) != 10:
                expected_nip = None
        
        cases.append({
            'input': str(input_name).strip(),
            'expected_nip': expected_nip,
            'row_number': idx + 1,  # 1-indexed for Excel
        })
    
    return cases


async def main():
    """Run chaotic batch test."""
    print("=" * 80)
    print("TEST: Chaotic Data Processing (Rows 150-200)")
    print("=" * 80)
    print()
    
    # Load test cases
    test_cases = load_test_cases()
    print(f"Loaded {len(test_cases)} test cases from Excel")
    print()
    
    # Initialize orchestrator
    orchestrator = CompanyIntelOrchestrator()
    
    # Track results
    results = []
    success_count = 0
    fail_count = 0
    
    # Run tests
    for i, test_case in enumerate(test_cases, 1):
        input_text = test_case['input']
        expected_nip = test_case['expected_nip']
        row_num = test_case['row_number']
        
        print(f"\n[{i}/{len(test_cases)}] Row {row_num}: '{input_text[:60]}...'")
        print(f"    Expected NIP: {expected_nip or 'N/A'}")
        
        try:
            # Call chaotic analyzer
            result = await orchestrator.analyze_chaotic(input_text)
            
            # Extract found NIP
            found_nip = None
            if result and result.get('nip_data'):
                nip_data = result['nip_data']
                if nip_data.get('found') and nip_data.get('nip'):
                    found_nip = nip_data['nip']
            
            # Compare
            is_success = False
            if expected_nip and found_nip:
                is_success = found_nip == expected_nip
            elif not expected_nip and not found_nip:
                is_success = True  # Both None is OK
            
            status = "OK" if is_success else "FAIL"
            if is_success:
                success_count += 1
            else:
                fail_count += 1
            
            print(f"    Found NIP: {found_nip or 'None'}")
            print(f"    Status: {status}")
            
            # Log strategy used
            if result and result.get('nip_data'):
                nip_data = result['nip_data']
                strategy = nip_data.get('strategy_used', 'N/A')
                confidence = nip_data.get('confidence', 0)
                print(f"    Strategy: {strategy}, Confidence: {confidence:.2f}")
            
            # Store result
            results.append({
                'row_number': row_num,
                'input': input_text,
                'expected_nip': expected_nip,
                'found_nip': found_nip,
                'success': is_success,
                'strategy': result.get('nip_data', {}).get('strategy_used') if result else None,
                'confidence': result.get('nip_data', {}).get('confidence', 0) if result else 0,
            })
            
        except Exception as e:
            print(f"    ERROR: {e}")
            fail_count += 1
            results.append({
                'row_number': row_num,
                'input': input_text,
                'expected_nip': expected_nip,
                'found_nip': None,
                'success': False,
                'error': str(e),
            })
    
    # Print summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    total = len(results)
    success_rate = (success_count / total * 100) if total > 0 else 0
    print(f"Total: {total}")
    print(f"Success: {success_count} ({success_rate:.1f}%)")
    print(f"Fail: {fail_count}")
    
    # Print failed cases
    failed = [r for r in results if not r['success']]
    if failed:
        print("\nFailed cases:")
        for r in failed:
            print(f"  Row {r['row_number']}: '{r['input'][:50]}...'")
            print(f"    Expected: {r['expected_nip']}, Found: {r['found_nip']}")
    
    # Save results to JSON
    output_file = f"test_chaotic_150_200_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'total': total,
            'success_count': success_count,
            'fail_count': fail_count,
            'success_rate': success_rate,
            'results': results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to: {output_file}")
    
    # Close orchestrator
    await orchestrator.close()
    
    return success_rate


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result >= 50 else 1)
