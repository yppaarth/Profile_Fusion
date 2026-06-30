"""Generate a realistic sample resume PDF for testing."""
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.units import inch
from reportlab.lib import colors

def generate():
    doc = SimpleDocTemplate(
        "data/resume.pdf",
        pagesize=letter,
        leftMargin=0.75*inch,
        rightMargin=0.75*inch,
        topMargin=0.75*inch,
        bottomMargin=0.75*inch,
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=18, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, spaceBefore=12, spaceAfter=4, textColor=colors.HexColor("#333333"))
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=10, leading=14)
    contact = ParagraphStyle("contact", parent=styles["Normal"], fontSize=10, textColor=colors.HexColor("#555555"))

    content = []

    content.append(Paragraph("Priya Sharma", h1))
    content.append(Paragraph("priya.sharma@email.com | +1 (415) 555-2671 | San Francisco, CA", contact))
    content.append(Paragraph("linkedin.com/in/priya-sharma-swe | github.com/priya-sharma-dev", contact))
    content.append(Spacer(1, 0.1*inch))

    content.append(Paragraph("Summary", h2))
    content.append(Paragraph(
        "Senior Software Engineer with 6+ years of experience building large-scale distributed systems "
        "and ML infrastructure. Passionate about high-throughput data pipelines, system reliability, "
        "and engineering excellence. Previously at Google and Stripe.",
        body
    ))

    content.append(Paragraph("Experience", h2))

    content.append(Paragraph("<b>Senior Software Engineer</b>", body))
    content.append(Paragraph("Stripe | Jan 2022 – Present", contact))
    content.append(Paragraph(
        "Led redesign of payment routing engine, cutting p99 latency by 40%. "
        "Built real-time fraud detection pipeline processing 50K TPS using Kafka and Flink. "
        "Mentored 3 junior engineers and drove team technical roadmap.",
        body
    ))
    content.append(Spacer(1, 0.08*inch))

    content.append(Paragraph("<b>Software Engineer II</b>", body))
    content.append(Paragraph("Google | Jun 2019 – Dec 2021", contact))
    content.append(Paragraph(
        "Contributed to BigQuery storage layer. Improved columnar compression algorithms "
        "reducing storage costs by 15%. Shipped features for 5M+ active users.",
        body
    ))
    content.append(Spacer(1, 0.08*inch))

    content.append(Paragraph("<b>Software Engineering Intern</b>", body))
    content.append(Paragraph("Microsoft | May 2018 – Aug 2018", contact))
    content.append(Paragraph(
        "Built automated regression testing tooling for Azure SDK. Reduced test cycle time by 30%.",
        body
    ))

    content.append(Paragraph("Education", h2))

    content.append(Paragraph("<b>Master of Science, Computer Science</b>", body))
    content.append(Paragraph("Carnegie Mellon University | 2017 – 2019", contact))
    content.append(Spacer(1, 0.05*inch))

    content.append(Paragraph("<b>Bachelor of Technology, Computer Science</b>", body))
    content.append(Paragraph("IIT Bombay | 2013 – 2017", contact))

    content.append(Paragraph("Skills", h2))
    content.append(Paragraph(
        "Python, Go, C++, Distributed Systems, Machine Learning, Apache Kafka, "
        "Kubernetes, AWS, PostgreSQL, TensorFlow, Docker, Redis, gRPC, Protocol Buffers",
        body
    ))

    doc.build(content)
    print("Generated data/resume.pdf")

if __name__ == "__main__":
    generate()
