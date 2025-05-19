from flask import Flask, render_template, request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, func
from datetime import date, datetime

app = Flask(__name__)
app.secret_key = 'your-very-secret-key'

# Database config
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+mysqlconnector://invigilationdb_loudatomup:2579baed22025cc45c8a56340c85426b33b4d69b@v5wu1.h.filess.io:61002/invigilationdb_loudatomup'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Models
class teacher(db.Model):
    __tablename__ = 'teachers'
    TeacherCode = db.Column(db.String(10), primary_key=True)
    FirstName = db.Column(db.String(50))
    LastName = db.Column(db.String(50))
    Role = db.Column(db.String(50))
    lessonCount = db.Column(db.Integer)
    cover_count = 0  # Not stored in DB; added dynamically

class covers(db.Model):
    __tablename__ = 'covers'
    CoverID = db.Column(db.Integer, primary_key=True)
    CoverTeacherCode = db.Column(db.String(10), db.ForeignKey('teachers.TeacherCode'))
    AbsentTeacherCode = db.Column(db.String(10))
    Date = db.Column(db.Date)
    Period = db.Column(db.String(10))
    Class = db.Column(db.String(50))
    Week = db.Column(db.String(1))

class coverrota(db.Model):
    __tablename__ = 'coverrota'
    RotaID = db.Column(db.Integer, primary_key=True)
    Day = db.Column(db.String(20))
    Period = db.Column(db.String(10))
    TeacherCode = db.Column(db.String(10), db.ForeignKey('teachers.TeacherCode'))
    Week = db.Column(db.String(1))

class lessonsWeekA(db.Model):
    __tablename__ = 'lessonsweeka'
    LessonID = db.Column(db.Integer, primary_key=True)
    TeacherCode = db.Column(db.String(50), db.ForeignKey('teachers.TeacherCode'))
    Subject = db.Column(db.String(50))
    Class = db.Column(db.String(50))
    Day = db.Column(db.String(50))
    Period = db.Column(db.String(50))
    Room = db.Column(db.String(50))

class lessonsWeekB(db.Model):
    __tablename__ = 'lessonsweekb'
    LessonID = db.Column(db.Integer, primary_key=True)
    TeacherCode = db.Column(db.String(50), db.ForeignKey('teachers.TeacherCode'))
    Subject = db.Column(db.String(50))
    Class = db.Column(db.String(50))
    Day = db.Column(db.String(50))
    Period = db.Column(db.String(50))
    Room = db.Column(db.String(50))

# ---------------------------
# Initialization Function
# ---------------------------
def initialize_app():
    teachers = teacher.query.all()

    cover_counts = dict(
        db.session.query(covers.CoverTeacherCode, func.count(covers.CoverID))
        .group_by(covers.CoverTeacherCode)
        .all()
    )

    for t in teachers:
        t.cover_count = cover_counts.get(t.TeacherCode, 0)

    app.teachers = teachers

# ---------------------------
# Routes
# ---------------------------

@app.route('/')
def home():
    if not hasattr(app, 'teachers') or not app.teachers:
        initialize_app()

    return render_template('cover_assignments.html', teachers=app.teachers, current_date=date.today().isoformat())

@app.route('/test_connection')
def test_connection():
    try:
        with db.engine.connect() as connection:
            connection.execute(text('SELECT 1'))
        return "Database connection is valid!"
    except Exception as e:
        return f"Database connection failed: {str(e)}"

@app.route('/mark_absent', methods=['POST'])
def mark_absent():
    selected_date = request.form.get('absence_date')
    selected_teachers = request.form.getlist('selected_teachers')
    week = request.form.get('week')
    exam_period = request.form.get('exam_period')

    date_obj = datetime.strptime(selected_date, "%Y-%m-%d")
    day_of_week = date_obj.strftime("%A")
    assigned_teachers_today = set()

    LessonModel = lessonsWeekA if week == 'A' else lessonsWeekB

    query = LessonModel.query.filter(
        LessonModel.TeacherCode.in_(selected_teachers),
        LessonModel.Day == day_of_week,
        LessonModel.Class != "free",
        LessonModel.Period != "Reg"
    )

    if exam_period == "yes":
        query = query.filter(
            ~LessonModel.Class.like('11%'),
            ~LessonModel.Class.like('13%')
        )

    lessons = query.all()
    lessons.sort(key=lambda l: l.Period)
    coverSuggestions = []

    for lesson in lessons:
        free_periods = getCoverTeachers(day_of_week, lesson, week, exam_period, selected_teachers, assigned_teachers_today)
        sorted_teachers = sort_teachers_by_availability(free_periods)

        if sorted_teachers:
            assigned_teacher = sorted_teachers[0]
            assigned_teachers_today.add(assigned_teacher.TeacherCode)
            reordered_teachers = [assigned_teacher] + [t for t in sorted_teachers if t.TeacherCode != assigned_teacher.TeacherCode]
        else:
            reordered_teachers = []

        coverSuggestions.append((lesson, reordered_teachers))

    return render_template('Output.html',
                           teachers=app.teachers,
                           coverSuggestions=coverSuggestions,
                           current_date=selected_date)

# ---------------------------
# Helpers
# ---------------------------

def score_teacher(t):
    role = t.Role.lower()
    expected = 58  # Default
    if "senior" in role:
        expected = 29
    elif "middle" in role:
        expected = 40.6

    lesson_ratio = t.lessonCount / expected if expected else 1
    return lesson_ratio + (t.cover_count * 0.05)

def sort_teachers_by_availability(teachers):
    return sorted(teachers, key=score_teacher)

def getCoverTeachers(day_of_week, lesson, week, exam_period, absent_teachers, already_assigned_today):
    LessonModel = lessonsWeekA if week == 'A' else lessonsWeekB

    rota_teacher_codes = [r.TeacherCode for r in coverrota.query.filter_by(
        Day=day_of_week, Period=lesson.Period, Week=week
    ).all()]

    free_periods = LessonModel.query.filter_by(
        Day=day_of_week, Period=lesson.Period
    ).all()

    free_teacher_codes = [
        l.TeacherCode for l in free_periods
        if (
            l.Class == "free" or
            (exam_period == "yes" and ("Y11" in l.Class or "Y13" in l.Class))
        ) and l.TeacherCode not in absent_teachers
    ]

    eligible_rota_teachers = [
        t for t in app.teachers
        if t.TeacherCode in rota_teacher_codes and t.TeacherCode in free_teacher_codes and t.TeacherCode not in already_assigned_today
    ]

    eligible_other_teachers = [
        t for t in app.teachers
        if t.TeacherCode not in rota_teacher_codes and t.TeacherCode in free_teacher_codes and t.TeacherCode not in already_assigned_today
    ]

    def penalize_if_assigned(t):
        return score_teacher(t) + (0.5 if t.TeacherCode in already_assigned_today else 0)

    eligible_rota_teachers.sort(key=penalize_if_assigned)
    eligible_other_teachers.sort(key=penalize_if_assigned)

    return eligible_rota_teachers or eligible_other_teachers

# ---------------------------
# Teardown to release DB connections
# ---------------------------
@app.teardown_appcontext
def shutdown_session(exception=None):
    db.session.remove()

# ---------------------------
# Run App
# ---------------------------
if __name__ == '__main__':
    with app.app_context():
        initialize_app()
    app.run(host='0.0.0.0', port=5000, debug=True)