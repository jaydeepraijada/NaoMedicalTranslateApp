from app import app, socketio

app.debug = False

if __name__ == '__main__':
    socketio.run(app)
