from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem

def generate_documentation():
    doc = SimpleDocTemplate(
        "Healthcare_Translation_App_Documentation.pdf",
        pagesize=letter,
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=72
    )
    
    styles = getSampleStyleSheet()
    story = []
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30
    )
    story.append(Paragraph("Healthcare Translation Web App Documentation", title_style))
    story.append(Spacer(1, 12))
    
    # 1. Executive Summary
    story.append(Paragraph("1. Executive Summary", styles['Heading1']))
    
    # Purpose and scope
    story.append(Paragraph("Purpose and Scope", styles['Heading2']))
    story.append(Paragraph("""
    The Healthcare Translation Web App is designed to facilitate real-time multilingual communication 
    in healthcare settings. It enables healthcare providers and patients to communicate effectively 
    across language barriers by providing instant voice-to-text translation with specialized medical 
    terminology support.
    """, styles['Normal']))
    
    # Key Features
    story.append(Paragraph("Key Features", styles['Heading2']))
    features = [
        "Real-time voice-to-text transcription",
        "Medical terminology validation and correction",
        "15 language support with automatic detection",
        "Voice synthesis for translated text",
        "Mobile-responsive interface",
        "Volume monitoring and audio quality checks"
    ]
    story.append(ListFlowable([ListItem(Paragraph(f, styles['Normal'])) for f in features], bulletType='bullet'))
    
    # Supported Languages
    story.append(Paragraph("Supported Languages", styles['Heading2']))
    languages = [
        "English", "Spanish", "French", "German", "Chinese", 
        "Hindi", "Japanese", "Korean", "Russian", "Arabic",
        "Portuguese", "Italian", "Dutch", "Polish", "Turkish"
    ]
    story.append(ListFlowable([ListItem(Paragraph(l, styles['Normal'])) for l in languages], bulletType='bullet'))
    
    # 2. Technical Overview
    story.append(Paragraph("2. Technical Overview", styles['Heading1']))
    
    # Speech Recognition
    story.append(Paragraph("Speech Recognition using OpenAI Whisper", styles['Heading2']))
    story.append(Paragraph("""
    The application utilizes OpenAI's Whisper API for accurate speech recognition, particularly 
    optimized for medical terminology. The system includes specialized context prompting to enhance 
    accuracy in medical contexts.
    """, styles['Normal']))
    
    # Medical Terminology Validation
    story.append(Paragraph("Medical Terminology Validation with GPT-4", styles['Heading2']))
    story.append(Paragraph("""
    GPT-4 powered validation system ensures medical terms are correctly transcribed and translated. 
    The system validates terminology, corrects common errors, and provides warnings for potentially 
    critical medical information.
    """, styles['Normal']))
    
    # Real-time Translation
    story.append(Paragraph("Real-time Translation System", styles['Heading2']))
    story.append(Paragraph("""
    Implements a robust translation pipeline using Google Translate API with medical context 
    preservation. The system includes specialized handling for medical terminology across all 
    supported languages.
    """, styles['Normal']))
    
    # Voice Synthesis
    story.append(Paragraph("Voice Synthesis Capabilities", styles['Heading2']))
    story.append(Paragraph("""
    Multi-layered voice synthesis system with fallback options:
    1. Browser-native speech synthesis
    2. Google Text-to-Speech API fallback
    3. Audio streaming fallback for unsupported languages
    """, styles['Normal']))
    
    # 3. Features Guide
    story.append(Paragraph("3. Features Guide", styles['Heading1']))
    
    features_guide = [
        ("Language Selection", """
        Select from 15 supported languages for both input and output. The interface provides 
        intuitive dropdown menus for language selection with real-time switching capabilities.
        """),
        ("Voice Recording and Transcription", """
        High-quality voice recording with volume monitoring and automatic silence detection. 
        The system provides real-time feedback on audio quality and speech detection.
        """),
        ("Medical Term Validation", """
        Automatic detection and validation of medical terminology, including dosages, 
        vital signs, and medical abbreviations. Provides immediate feedback on potential errors.
        """),
        ("Translation Display", """
        Dual-panel interface showing original and translated text in real-time. 
        Includes visual indicators for translation progress and quality.
        """),
        ("Audio Playback", """
        High-quality text-to-speech synthesis with support for medical terminology pronunciation. 
        Multiple fallback options ensure consistent audio output across all languages.
        """)
    ]
    
    for title, content in features_guide:
        story.append(Paragraph(title, styles['Heading2']))
        story.append(Paragraph(content, styles['Normal']))
    
    # 4. User Instructions
    story.append(Paragraph("4. User Instructions", styles['Heading1']))
    
    instructions = [
        ("Step 1", "Select your desired input and output languages from the dropdown menus."),
        ("Step 2", "Click 'Test Microphone' to verify your audio input is working correctly."),
        ("Step 3", "Press 'Start Recording' and speak clearly into your microphone."),
        ("Step 4", "Monitor the volume meter to ensure optimal audio levels."),
        ("Step 5", "Review the transcribed text and medical term validations."),
        ("Step 6", "Click 'Speak Translation' to hear the translated text.")
    ]
    
    for step, instruction in instructions:
        story.append(Paragraph(step, styles['Heading3']))
        story.append(Paragraph(instruction, styles['Normal']))
    
    # 5. Security & Privacy
    story.append(Paragraph("5. Security & Privacy", styles['Heading1']))
    
    security_topics = [
        ("Data Handling", """
        All audio and text data is processed in real-time and not stored permanently. 
        Temporary buffers are cleared immediately after processing.
        """),
        ("API Security", """
        All API communications are encrypted using HTTPS. API keys are securely managed 
        using environment variables and never exposed to the client side.
        """),
        ("Medical Information Privacy", """
        The application follows healthcare privacy guidelines. No patient information 
        is stored or logged. All processing occurs in memory and is immediately discarded.
        """)
    ]
    
    for title, content in security_topics:
        story.append(Paragraph(title, styles['Heading2']))
        story.append(Paragraph(content, styles['Normal']))
    
    doc.build(story)

if __name__ == "__main__":
    generate_documentation()
