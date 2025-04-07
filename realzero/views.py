from django.shortcuts import render, get_object_or_404
from .models import realzero
from django.db.models import Q
from django.utils import timezone
import os
import json
from google.cloud import vision
import re

def index(request):
    return render(request, 'homepage/index.html')

def ranking(request):
    return render(request, 'homepage/ranking.html')

def community(request):
    return render(request, 'homepage/community.html')

def search(request):
    query = request.GET.get('q', '').strip()
    filter_option = request.GET.get('maltitol_filter', '')
    results = realzero.objects.all()

    if query:
        results = results.filter(
            Q(product_name__icontains=query) |
            Q(Manufacturer__icontains=query)
        )

        # ✅ 말티톨 필터 옵션 처리
        if filter_option == 'include':
            results = results.filter(
                Q(Raw_materials__icontains='말티톨') |
                Q(Raw_materials__icontains='폴리글리시톨시럽')
            )

        elif filter_option == 'exclude':
            results = results.exclude(
                Q(Raw_materials__icontains='말티톨') |
                Q(Raw_materials__icontains='폴리글리시톨시럽')
            )

    else:
        results = []

    # 결과가 있으면 → 결과 템플릿으로 렌더
    if results:
        return render(request, 'homepage/search_results.html', {
            'query': query,
            'results': results,
            'count': results.count(),
            'filter_option': filter_option  # 👉 템플릿에서 select 유지용
        })

    # 결과가 없으면 → search_fail.html (OCR 기능 포함)
    context = {
        'query': query,
        'filter_option': filter_option
    }

    if request.method == "POST" and 'file' in request.FILES:
        image_content = request.FILES['file'].read()
        result = detect_text(image_content)
        context.update({
            "text": result["text"],
            "message": result["message"],
            "warning": result["warning"]
        })

    return render(request, 'homepage/search_fail.html', context)

def product_detail(request, id):
    product = get_object_or_404(realzero, id=id)

    raw_materials = product.Raw_materials.lower() if product.Raw_materials else ""
    has_maltitol = "말티톨" in raw_materials or "maltitol" in raw_materials
    
    cal_value_raw = (product.Product_calorific_value or "").strip().lower()
    try:
        cal_value = float(re.search(r'[\d.]+', cal_value_raw).group())
    except (AttributeError, ValueError):
        cal_value = 0

    # 용량 값 가져오기 및 숫자 추출
    capacity_raw = (product.Product_calorific_onetime or "").strip().lower()
    try:
        capacity = float(re.search(r'[\d.]+', capacity_raw).group())
    except (AttributeError, ValueError):
        capacity = 1

    # 기본 0칼로리 여부 확인
    is_zero_calorie = cal_value_raw in ["0", "0kcal", "0 kcal"]

    # 단위당 칼로리 계산 및 0칼로리 여부 확인
    calories_per_unit = 0
    if not is_zero_calorie and capacity > 0:
        calories_per_unit = cal_value / capacity
        is_zero_calorie = calories_per_unit <= 0.05

    materials_list = [item.strip() for item in product.Raw_materials.split(',') if item.strip()]

    # 혈당 주의 성분 관련 메시지
    blacklist = ["말티톨시럽", "말티톨", "폴리글리시톨시럽", "물엿", "자일리톨"]
    blacklist = sorted(blacklist, key=len, reverse=True)

    highlighted_materials = []
    matched_keywords = set()  # 중복 방지용

    for material in materials_list:
        highlighted = material
        for keyword in blacklist:
            if keyword in highlighted:
                highlighted = highlighted.replace(
                    keyword, f"<span class='text-danger'>{keyword}</span>"
                )
                matched_keywords.add(keyword)
        highlighted_materials.append(highlighted)

    warning_groups = {
    "말티톨": ["말티톨", "말티톨시럽"],
    "폴리글리시톨시럽": ["폴리글리시톨시럽"],
    "물엿": ["물엿"],
    "자일리톨": ["자일리톨"]
    }

    warnings_count = 0
    for group in warning_groups.values():
        if any(kw in raw_materials for kw in group):
            warnings_count += 1

    blood_sugar_warning = any(keyword in raw_materials for keyword in blacklist)
    missing_gi = not product.GI or str(product.GI).strip().lower() in ['null', '측정불가']

    warning_messages = []
    if blood_sugar_warning:
        warning_messages.append("혈당에 영향을 주는 대체당 성분이 있습니다.")
    if missing_gi:
        warning_messages.append("대체당 함유량이 명확히 표시되어 있지 않습니다.")

    return render(request, 'homepage/product_detail.html', {
        'product': product,
        'materials_list': materials_list,
        'highlighted_materials': highlighted_materials,
        'warnings_count': warnings_count,
        'has_maltitol': has_maltitol,
        'is_zero_calorie': is_zero_calorie,
        'warning_messages': warning_messages, # 👈 템플릿에서 사용할 리스트
        'total_calories': cal_value,
        'capacity': capacity,

    })

def ranking_view(request):
    all_products = realzero.objects.order_by('id')
    stepped_products = all_products[::3][:10]
    return render(request, 'homepage/ranking.html', {
        'products': stepped_products
    })

# Google Cloud Vision API 인증 설정
credentials_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ocr-text-extraction_api_key.json")
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = credentials_path

# JSON 파일 유효성 검사
if credentials_path and os.path.exists(credentials_path):
    try:
        with open(credentials_path, 'r') as file:
            data = json.load(file)
        required_keys = ["type", "project_id"]
        missing_keys = [key for key in required_keys if key not in data]
        if not missing_keys:
            print("JSON 파일이 올바릅니다.")
        else:
            print(f"JSON 파일에서 누락된 키가 있습니다 {missing_keys}")
    except json.JSONDecodeError as e:
        print(f"JSON 파일을 해석하는 중 오류 발생:  {e}")
else:
    print(f"GOOGLE_APPLICATION_CREDENTIALS 환경 변수가 설정되지 않았거나, 파일이 존재하지 않습니다: {credentials_path}")

# 텍스트 감지 함수 (OCR)
def detect_text(image_content):
    client = vision.ImageAnnotatorClient()
    image = vision.Image(content=image_content)
    # image_content → 사용자가 올린 사진 데이터를 가져온다.
    response = client.text_detection(image=image)
    # 사진속 텍스트 감지
    texts = response.text_annotations
    # 찾은 글자 정보 가져와 texts에 담는다.
    if not texts:
        return {"text": "text=x", "warning": None}
    
    # OCR 결과에서 첫 번째 요소가 전체 텍스트 (이후의 요소들은 개별 단어 정보)
    extracted_text = texts[0].description if texts else ""

    blacklist = ["말티톨", "물엿", "폴리글리시톨시럽", "자일리톨"]
    ingredients = []
    print("extracted_text",extracted_text)
        # 모든 blacklist 단어를 빨간색으로 표시
    highlighted_text = extracted_text  # 원본 텍스트 유지
    for ingredient in blacklist:
        if ingredient in extracted_text:
            highlighted_text = highlighted_text.replace(
                ingredient, f"<span class='text-danger'>{ingredient}</span>"
            )
            ingredients.append(ingredient)  # 감지된 성분 추가
            
    # 경고 메시지 추가 (대체당 성분이 없을 때)      
    message = None
    if "당알콜" not in extracted_text:
        message = (
            "⚠ 경고: 이 제품에는 대체당 성분이 명확하게 표시되어 있지 않습니다."
        )

    # 경고 메시지 추가 (검출된 성분이 있을 때만)
    warning_message = None
    if ingredients:
        warning_message = (
            "⚠ 경고: 이 제품에는 혈당을 올리는 성분이 포함되어 있습니다. "
            "과량 섭취 시 설사를 유발할 수 있습니다."
        )

    return {"text": highlighted_text, "warning": warning_message, "message" :  message}

def index(request):
    # 최근 등록된 제품 5개
    new_products = realzero.objects.order_by('id')[4::3][:5]

    all_products = realzero.objects.order_by('id')
    stepped_products = all_products[::3][:5]

    return render(request, 'homepage/index.html', {
        'new_products': new_products,
        'popular_products': stepped_products
    })

def community_content(request):
    banners = [
        {"image": "/static/homepage/img/content_1.jpg", "url": "https://www.youtube.com/watch?v=PMIPTYRC0wY&t=35s"},
        {"image": "/static/homepage/img/content_2.jpg", "url": "https://www.youtube.com/watch?v=sZHNoczmeD4"},
        {"image": "/static/homepage/img/content_3.jpg", "url": "https://www.youtube.com/watch?v=AcHpPET-Mwk&t=64s"},
    ]

    posts = [
        {"title": "이 제품 음료 어때요?", "author": "최민서", "created_at": timezone.now(), "views": 93},
        {"title": "이거 말티톨 썼네 ㅡㅡ", "author": "송동규", "created_at": timezone.now(), "views": 733},
        {"title": "새로 나왔는데 맛있네요!", "author": "이재현", "created_at": timezone.now(), "views": 413},
        {"title": "혈당 이 정도면 괜찮나요?", "author": "양지웅", "created_at": timezone.now(), "views": 234},
        {"title": "이 레시피 좋네요!", "author": "주승완", "created_at": timezone.now(), "views": 113},
    ]

    return render(request, 'homepage/community.html', {
        "banners": banners,
        "posts": posts,
    })