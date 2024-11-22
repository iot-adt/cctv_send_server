from flask import Flask
from flask_sock import Sock
import cv2
import base64
import threading
import time

app = Flask(__name__)
sock = Sock(app)

# 카메라 설정
camera = cv2.VideoCapture(0)
camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

clients = []  # 클라이언트 소켓 리스트
modes = {}  # 클라이언트별 모드 저장 (일반/보안)

# 움직임 감지용 기준 프레임 초기화
static_back = None

def send_frames():
    global clients, modes
    while True:
        if len(clients) > 0:
            ret, frame = camera.read()
            if not ret:
                continue

            for ws in clients:
                try:
                    # 클라이언트의 모드 확인
                    mode = modes.get(ws, "normal")  # 기본값: 일반(normal)

                    if mode == "secure":
                        # 보안 모드: 움직임 감지
                        frame = detect_motion(frame)
                    
                    # 흑백 변환 (일반/보안 모드 공통)
                    gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

                    # JPEG로 인코딩
                    _, buffer = cv2.imencode('.jpg', gray_frame)
                    encoded_frame = base64.b64encode(buffer).decode('utf-8')

                    # 클라이언트에 전송
                    ws.send(encoded_frame)
                except:
                    clients.remove(ws)
                    if ws in modes:
                        del modes[ws]

        time.sleep(0.03)

def detect_motion(frame):
    """움직임 감지 및 사각형 박스 그리기"""
    global static_back  # 전역 변수 선언
    gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray_frame = cv2.GaussianBlur(gray_frame, (21, 21), 0)

    if static_back is None:
        static_back = gray_frame
        return frame

    # 차이 계산
    diff_frame = cv2.absdiff(static_back, gray_frame)
    thresh_frame = cv2.threshold(diff_frame, 30, 255, cv2.THRESH_BINARY)[1]
    thresh_frame = cv2.dilate(thresh_frame, None, iterations=2)

    # 컨투어 찾기
    contours, _ = cv2.findContours(thresh_frame, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        if cv2.contourArea(contour) < 1000:  # 작은 노이즈 제거
            continue
        (x, y, w, h) = cv2.boundingRect(contour)
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 3)

    return frame

@sock.route('/video')
def video(ws):
    global clients, modes
    clients.append(ws)
    modes[ws] = "normal"  # 기본 모드: 일반
    while True:
        try:
            message = ws.receive()
            if message is None:
                break

            # 클라이언트에서 모드 변경 요청 처리
            if message == "secure":
                modes[ws] = "secure"
            elif message == "normal":
                modes[ws] = "normal"
        except:
            break
    clients.remove(ws)
    if ws in modes:
        del modes[ws]

@app.route("/")
def root():
    # HTML이 필요 없는 경우 간단한 JSON 응답 반환
    return {"status": "Streaming server is running"}

if __name__ == "__main__":
    thread = threading.Thread(target=send_frames, daemon=True)
    thread.start()

    app.run(host="0.0.0.0", port=5000)
