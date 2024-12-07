from flask import Flask
from flask_sock import Sock
import cv2
import base64
import threading
import time
import requests

app = Flask(__name__)
sock = Sock(app)

# 카메라 설정
camera = cv2.VideoCapture(0)
camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

clients = []  # 클라이언트 소켓 리스트
modes = {}  # 클라이언트별 모드 저장 (일반/보안)
prev_frames = {}  # 클라이언트별 이전 프레임 저장

BUZZER_SERVER_URL = "http://192.168.1.163:8080/trigger-buzzer"

def send_frames():
    global clients, modes, prev_frames
    while True:
        if len(clients) > 0:
            ret, frame = camera.read()
            if not ret:
                continue

            # 리스트를 복사하여 순회 중 수정 문제 방지
            current_clients = clients.copy()
            for ws in current_clients:
                try:
                    # 클라이언트의 모드 확인
                    mode = modes.get(ws, "normal")  # 기본값: 일반(normal)

                    # 현재 프레임 복사
                    current_frame = frame.copy()

                    if mode == "secure":
                        print(f"Processing secure mode for client")
                        # 보안 모드: 움직임 감지
                        current_frame = detect_motion(current_frame, ws)
                    
                    # 흑백 변환 (일반/보안 모드 공통)
                    gray_frame = cv2.cvtColor(current_frame, cv2.COLOR_BGR2GRAY)

                    # JPEG로 인코딩
                    _, buffer = cv2.imencode('.jpg', gray_frame)
                    encoded_frame = base64.b64encode(buffer).decode('utf-8')

                    # 클라이언트에 전송
                    print(f"Sending frame in {mode} mode")
                    ws.send(encoded_frame)
                except Exception as e:
                    print(f"Error in send_frames: {str(e)}")
                    if ws in clients:
                        clients.remove(ws)
                    if ws in modes:
                        del modes[ws]
                    if ws in prev_frames:
                        del prev_frames[ws]

        time.sleep(0.03)


def detect_motion(frame, ws):
    """2프레임 기반 움직임 감지 및 사각형 표시"""
    global prev_frames
    try:
        # 현재 프레임을 흑백 및 블러 처리
        gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray_frame = cv2.GaussianBlur(gray_frame, (21, 21), 0)

        if ws not in prev_frames:
            print("Initializing prev_frame for client")
            prev_frames[ws] = gray_frame
            return frame

        # 두 프레임 간 차이 계산
        diff_frame = cv2.absdiff(prev_frames[ws], gray_frame)

        # 차이를 이진화 (임계값 적용)
        _, thresh_frame = cv2.threshold(diff_frame, 25, 255, cv2.THRESH_BINARY)

        # 노이즈 제거 (모폴로지 연산)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        thresh_frame = cv2.morphologyEx(thresh_frame, cv2.MORPH_CLOSE, kernel)
        thresh_frame = cv2.dilate(thresh_frame, None, iterations=2)

        # 움직임 감지
        motion_detected = False
        contours, _ = cv2.findContours(thresh_frame, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            if cv2.contourArea(contour) < 1000:  # 작은 움직임 무시
                continue
            motion_detected = True
            (x, y, w, h) = cv2.boundingRect(contour)
            cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 255, 255), 2)
            cv2.putText(frame, 'Motion Detected', (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        # 이전 프레임 갱신
        prev_frames[ws] = gray_frame

        return frame
    except Exception as e:
        print(f"Error in detect_motion: {str(e)}")
        return frame

def send_buzzer_signal():
    #http request
    try:
        response = requests.post(BUZZER_SERVER_URL, json = {"motion": True})
        if response.status_code==200:
            print("sign succes")
        else:
            print("sign fail")
    except Exception as e :
        print(f"error : {e}")


@sock.route('/video')
def video(ws):
    global clients, modes, prev_frames
    try:
        print("New client connected")
        clients.append(ws)
        modes[ws] = "normal"  # 기본 모드: 일반
        while True:
            try:
                message = ws.receive()
                print(f"Received message: {message}")
                
                if message is None:
                    break

                # 클라이언트에서 모드 변경 요청 처리
                if message == "secure":
                    print("Switching to secure mode")
                    modes[ws] = "secure"
                elif message == "normal":
                    print("Switching to normal mode")
                    modes[ws] = "normal"
            except Exception as e:
                print(f"Error in websocket loop: {str(e)}")
                break
    finally:
        print("Client disconnected, cleaning up")
        if ws in clients:
            clients.remove(ws)
        if ws in modes:
            del modes[ws]
        if ws in prev_frames:
            del prev_frames[ws]


@app.route("/")
def root():
    # HTML이 필요 없는 경우 간단한 JSON 응답 반환
    return {"status": "Streaming server is running"}


if __name__ == "__main__":
    thread = threading.Thread(target=send_frames, daemon=True)
    thread.start()

    app.run(host="0.0.0.0", port=5050)
