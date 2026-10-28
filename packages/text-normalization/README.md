# Offline text extraction boundary

`plain_text` uses the bounded MIME parser from the feasibility spike. It never follows links or loads remote resources, and returns unavailable for bodies without an eligible plain-text part. HTML/quote/signature segmentation and statistical language eligibility remain the planned extraction milestone.
