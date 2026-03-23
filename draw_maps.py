import openrouteservice
import folium

# 1. Khởi tạo client với API Key của bạn
# (Nhớ thay chuỗi bên dưới bằng API Key thật của bạn nhé)
api_key = '' 
client = openrouteservice.Client(key=api_key)

# 2. Khai báo tọa độ (Lưu ý quan trọng: ORS dùng định dạng [Kinh độ, Vĩ độ])
# Điểm A: Chợ Bến Thành | Điểm B: Landmark 81
start_coord = [106.6976, 10.7725]  # [Longitude, Latitude]
end_coord = [106.7218, 10.7950]

# 3. Gọi API để lấy dữ liệu đường đi (trả về dưới dạng GeoJSON)
route = client.directions(
    coordinates=[start_coord, end_coord],
    profile='driving-car',
    format='geojson'
)

# --- PHẦN MỚI: Lấy thông tin khoảng cách và thời gian ---
# Truy cập vào phần 'summary' trong dữ liệu GeoJSON trả về
summary = route['features'][0]['properties']['summary']

distance_meters = summary['distance']  # Khoảng cách (mét)
duration_seconds = summary['duration'] # Thời gian (giây)

# Chuyển đổi sang đơn vị dễ đọc hơn (Km và Phút)
distance_km = distance_meters / 1000
duration_minutes = duration_seconds / 60

print(f"Khoảng cách tuyến đường: {distance_km:.2f} km")
print(f"Thời gian di chuyển dự kiến: {duration_minutes:.0f} phút")

# 4. Tạo bản đồ bằng Folium
# Folium lại dùng định dạng [Vĩ độ, Kinh độ] nên ta đảo ngược tọa độ của điểm bắt đầu để canh giữa bản đồ
map_center = [start_coord[1], start_coord[0]] 
my_map = folium.Map(location=map_center, zoom_start=14)

thong_tin = f"<b>Landmark 81</b><br>Cách: {distance_km:.2f} km<br>Đi mất: {duration_minutes:.0f} phút"

# 5. Vẽ đường đi (dữ liệu GeoJSON) lên bản đồ
folium.GeoJson(
    route,
    name='Đường đi ô tô',
    style_function=lambda x: {'color': '#FF0000', 'weight': 5} # Đường màu đỏ, độ dày 5
).add_to(my_map)

# 6. Thêm Marker (điểm đánh dấu) cho điểm đầu và điểm cuối
folium.Marker(
    location=[start_coord[1], start_coord[0]],
    popup="Chợ Bến Thành",
    icon=folium.Icon(color="green", icon="play")
).add_to(my_map)

folium.Marker(
    location=[end_coord[1], end_coord[0]],
    popup="Landmark 81",
    icon=folium.Icon(color="red", icon="stop")
).add_to(my_map)

folium.Marker(
    location=[end_coord[1], end_coord[0]],
    popup=folium.Popup(thong_tin, max_width=200), # Đưa thông tin vào Popup
    icon=folium.Icon(color="red", icon="info-sign")
).add_to(my_map)

# 7. Lưu bản đồ thành file HTML
my_map.save('ban_do_cua_toi.html')
print("Đã tạo bản đồ thành công! Hãy mở file 'ban_do_cua_toi.html' trên trình duyệt để xem.")