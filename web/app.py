"""
Flask Web Application for Motor Insurance Fraud Detection
Clean professional web interface with real-time agent streaming
"""

from flask import Flask, render_template, request, jsonify, stream_with_context, Response
from main import ClaimAssessmentOrchestrator, ClaimData
import json
import os
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'motor-fraud-detection-2024'

# Global orchestrator (initialize once)
try:
    orchestrator = ClaimAssessmentOrchestrator()
    system_ready = True
except Exception as e:
    system_ready = False
    error_message = str(e)

# ============================================================================
# ROUTES
# ============================================================================

@app.route('/')
def index():
    """Main page with claim assessment form"""
    return render_template('index.html', system_ready=system_ready)


@app.route('/api/system-status')
def system_status():
    """Check if system is ready"""
    return jsonify({
        'status': 'ready' if system_ready else 'error',
        'message': 'System initialized' if system_ready else error_message
    })


@app.route('/api/assess-claim', methods=['POST'])
def assess_claim():
    """
    Assess a claim and stream results in real-time.
    Accepts JSON with claim details.
    """
    
    if not system_ready:
        return jsonify({'error': 'System not initialized'}), 500
    
    try:
        data = request.json
        
        # Validate required fields
        required_fields = [
            'claim_id', 'claimant_name', 'dl_number', 'rc_number',
            'vehicle_make', 'vehicle_segment', 'vehicle_idv',
            'claim_amount', 'days_policy_to_accident',
            'workshop_fraud_rate', 'witness_reuse_count',
            'fir_delay_days', 'distance_home_to_accident_km'
        ]
        
        missing = [f for f in required_fields if f not in data or data[f] is None]
        if missing:
            return jsonify({'error': f'Missing fields: {", ".join(missing)}'}), 400
        
        # Create claim object
        claim = ClaimData({
            'claim_id': data['claim_id'],
            'claimant_name': data['claimant_name'],
            'dl_number': data['dl_number'],
            'rc_number': data['rc_number'],
            'vehicle_make': data['vehicle_make'],
            'vehicle_segment': data['vehicle_segment'],
            'vehicle_age': int(data.get('vehicle_age', 5)),
            'vehicle_idv': int(data['vehicle_idv']),
            'claim_amount': int(data['claim_amount']),
            'accident_description': data.get('accident_description', 'Motor accident'),
            'days_policy_to_accident': int(data['days_policy_to_accident']),
            'injury_claimed': data.get('injury_claimed', False),
            'fir_number': data.get('fir_number', ''),
            'workshop_id': data.get('workshop_id', 'WS-0001'),
            'workshop_fraud_rate': float(data['workshop_fraud_rate']),
            'witness_reuse_count': int(data['witness_reuse_count']),
            'fir_delay_days': int(data['fir_delay_days']),
            'distance_home_to_accident_km': float(data['distance_home_to_accident_km']),
        })
        
        # Stream assessment results
        def generate_assessment():
            """Generator function to stream results"""
            
            # Start assessment
            yield f"data: {json.dumps({'type': 'status', 'message': 'Starting assessment...', 'progress': 5})}\n\n"
            
            try:
                # Run assessment
                results = orchestrator.assess_claim(claim)
                
                yield f"data: {json.dumps({'type': 'status', 'message': 'Document verification complete', 'progress': 50})}\n\n"
                
                # Send document results
                doc_pass = sum(1 for v in results['document_verification'].values() if v == 'PASS')
                doc_total = len(results['document_verification'])
                
                yield f"data: {json.dumps({
                    'type': 'document_verification',
                    'passed': doc_pass,
                    'total': doc_total,
                    'percentage': (doc_pass / doc_total * 100) if doc_total > 0 else 0,
                    'details': results['document_verification']
                })}\n\n"
                
                yield f"data: {json.dumps({'type': 'status', 'message': 'Fraud detection analysis complete', 'progress': 75})}\n\n"
                
                # Send fraud detection results
                fraud_prob = results['fraud_detection'].get('fraud_probability', 0.5)
                trigger_count = results['fraud_detection'].get('trigger_count', 0)
                
                yield f"data: {json.dumps({
                    'type': 'fraud_detection',
                    'fraud_probability': fraud_prob,
                    'fraud_percentage': fraud_prob * 100,
                    'trigger_count': trigger_count,
                    'risk_level': 'HIGH' if fraud_prob > 0.7 else ('MEDIUM' if fraud_prob > 0.5 else 'LOW')
                })}\n\n"
                
                # Send final verdict
                verdict = results['overall_verdict']
                if verdict == 'INVESTIGATE':
                    verdict_display = '🚨 HOLD FOR INVESTIGATION'
                    verdict_color = 'danger'
                elif verdict == 'REVIEW':
                    verdict_display = '⚠️  HOLD FOR REVIEW'
                    verdict_color = 'warning'
                else:
                    verdict_display = '✓ APPROVE'
                    verdict_color = 'success'
                
                yield f"data: {json.dumps({
                    'type': 'final_verdict',
                    'verdict': verdict,
                    'verdict_display': verdict_display,
                    'verdict_color': verdict_color,
                    'message': f'Assessment complete. Claim recommendation: {verdict_display}',
                    'progress': 100
                })}\n\n"
                
                # Send complete results
                yield f"data: {json.dumps({
                    'type': 'complete',
                    'results': {
                        'claim_id': claim.claim_id,
                        'document_pass_percentage': (doc_pass / doc_total * 100) if doc_total > 0 else 0,
                        'fraud_probability': fraud_prob,
                        'overall_verdict': verdict,
                        'recommendation': generate_recommendation(doc_pass, doc_total, fraud_prob)
                    }
                })}\n\n"
                
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': f'Assessment error: {str(e)}'})}\n\n"
        
        return Response(stream_with_context(generate_assessment()), mimetype='text/event-stream')
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/sample-claim')
def get_sample_claim():
    """Return a sample claim for testing"""
    sample = {
        'claim_id': 'CLM-2024-001',
        'claimant_name': 'Raj Kumar',
        'dl_number': 'DL-MH-2015-123456',
        'rc_number': 'DL-01-AB-2015-00001',
        'vehicle_make': 'Maruti',
        'vehicle_segment': 'Hatchback',
        'vehicle_age': 5,
        'vehicle_idv': 800000,
        'claim_amount': 550000,
        'accident_description': 'Front bumper damage in parking lot collision',
        'days_policy_to_accident': 3,
        'injury_claimed': False,
        'fir_number': 'FIR-2024-001',
        'workshop_id': 'WS-0026',
        'workshop_fraud_rate': 0.158,
        'witness_reuse_count': 3,
        'fir_delay_days': 6,
        'distance_home_to_accident_km': 186.4,
    }
    return jsonify(sample)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def generate_recommendation(doc_pass, doc_total, fraud_prob):
    """Generate recommendation based on assessment results"""
    
    if doc_pass < doc_total * 0.7:
        return "⚠️  Document verification failed. Recommend immediate investigation."
    
    if fraud_prob > 0.7:
        return "🚨 Strong fraud indicators detected. Request police verification and independent survey."
    elif fraud_prob > 0.5:
        return "⚠️  Moderate fraud risk. Request additional documentation and clarification."
    else:
        return "✓ Low fraud risk. Claim appears legitimate. May proceed with settlement."


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def server_error(error):
    return jsonify({'error': 'Server error'}), 500


# ============================================================================
# RUN APP
# ============================================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))

    print("=" * 80)
    print("Motor Insurance Fraud Detection — Web Interface")
    print("=" * 80)
    print(f"System Status: {'✓ READY' if system_ready else '✗ ERROR'}")
    print(f"Starting Flask server on: 0.0.0.0:{port}")
    print("=" * 80)

    app.run(
        debug=False,
        host='0.0.0.0',
        port=port,
        use_reloader=False
    )
