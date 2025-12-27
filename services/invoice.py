from django.template.loader import get_template
from django.http import HttpResponse
from xhtml2pdf import pisa
from io import BytesIO

class InvoiceService:
    @staticmethod
    def generate_invoice_pdf(order):
        template_path = 'emails/order_confirmation.html' # Reuse email template for now or create specific invoice
        # Ideally create 'store/invoice.html' that is print-friendly
        context = {'order': order}
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="invoice_{order.reference}.pdf"'
        
        template = get_template(template_path)
        html = template.render(context)
        
        pisa_status = pisa.CreatePDF(html, dest=response)
        
        if pisa_status.err:
            return HttpResponse('We had some errors <pre>' + html + '</pre>')
        return response
