"""Public quotation catalogue. Never rewrites contracts or subscription grants."""
PLANS = ('starter', 'standard', 'professional')
BANDS = [
    {'limit': 100, 'label': '0–100', 'prices': [30, 45, 65], 'setup': 0},
    {'limit': 300, 'label': '101–300', 'prices': [40, 60, 85], 'setup': 25},
    {'limit': 600, 'label': '301–600', 'prices': [55, 80, 115], 'setup': 40},
    {'limit': 1000, 'label': '601–1,000', 'prices': [75, 110, 155], 'setup': 60},
    {'limit': 2000, 'label': '1,001–2,000', 'prices': [100, 150, 220], 'setup': 90},
]
ADDONS = [
    {'code': 'finance', 'label': 'Advanced Finance & Accounting', 'price': 15, 'included': ['professional']},
    {'code': 'payroll', 'label': 'Payroll & HR', 'price': 15, 'included': ['professional']},
    {'code': 'library', 'label': 'Library Management', 'price': 8, 'included': ['standard', 'professional']},
    {'code': 'inventory', 'label': 'Inventory & Assets', 'price': 8, 'included': ['standard', 'professional']},
    {'code': 'lms', 'label': 'Learning Management System', 'price': 15, 'included': ['professional']},
    {'code': 'analytics', 'label': 'Advanced Analytics', 'price': 10, 'included': ['professional']},
    {'code': 'communications', 'label': 'Communication Automation', 'price': 8, 'included': []},
    {'code': 'api', 'label': 'API Integrations', 'price': 20, 'included': [], 'from_price': True},
]
FEATURES = {
    'Starter': ['School dashboard', 'Student records', 'Admissions and enrolment', 'Staff and user management', 'Classes and subjects', 'Basic school fees and receipting', 'Student balances and debt lists', 'Attendance', 'Basic academic reporting', 'Teacher dashboard', 'Student portal'],
    'Standard': ['Everything in Starter', 'Parent portal', 'Timetable management', 'Advanced examinations', 'Advanced school fee billing', 'Debt management and collection dashboards', 'Parent communication', 'Library management', 'Inventory and asset management'],
    'Professional': ['Everything in Standard', 'Advanced finance and accounting', 'Payroll and HR', 'Learning management system', 'Advanced analytics and reporting'],
}


def quote(enrolment, plan, addons=()):
    if isinstance(enrolment, bool) or not isinstance(enrolment, int) or enrolment < 0:
        raise ValueError('Enter a non-negative whole student enrolment.')
    if plan not in (*PLANS, 'enterprise'):
        raise ValueError('Choose a valid plan.')
    selected = set(addons)
    if selected - {item['code'] for item in ADDONS}:
        raise ValueError('Choose valid optional modules.')
    if enrolment > 2000 or plan == 'enterprise':
        return {'custom': True}
    band = next(item for item in BANDS if enrolment <= item['limit'])
    subscription = band['prices'][PLANS.index(plan)]
    extra = sum(item['price'] for item in ADDONS if item['code'] in selected and plan not in item['included'])
    return {'custom': False, 'subscription': subscription, 'addons': extra, 'setup': band['setup'],
            'first_term': subscription + extra + band['setup'], 'annual': 3 * (subscription + extra),
            'from_price': 'api' in selected}
