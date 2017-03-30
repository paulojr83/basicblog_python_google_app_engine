import os
import re
import random
import hashlib
import hmac
import webapp2
import jinja2

from google.appengine.ext import db
from string import letters

template_dir = os.path.join(os.path.dirname(__file__), 'templates')
jinja_env = jinja2.Environment(loader=jinja2.FileSystemLoader(template_dir),
                               autoescape=True)
SECRET = 'fart'

def render_str(template, **params):
    t = jinja_env.get_template(template)
    return t.render(params)

def make_secure_val(val):
    return '%s|%s' % (val, hmac.new(SECRET, val).hexdigest())

def check_secure_val(secure_val):
    val = secure_val.split('|')[0]
    if secure_val == make_secure_val(val):
        return val

class Handler(webapp2.RequestHandler):
    def write(self, *a, **kw):
        self.response.out.write(*a, **kw)

    def render_str(self, template, **params):
        params['user'] = self.user
        return render_str(template, **params)

    def render(self, template, **kw):
        self.write(self.render_str(template, **kw))

    def set_secure_cookie(self, name, val):
        cookie_val = make_secure_val(val)
        self.response.headers.add_header(
            'Set-Cookie',
            '%s=%s; Path=/' % (name, cookie_val))

    def read_secure_cookie(self, name):
        cookie_val = self.request.cookies.get(name)
        return cookie_val and check_secure_val(cookie_val)

    def login(self, user):
        self.set_secure_cookie('user_id', str(user.key().id()))

    def logout(self):
        self.response.headers.add_header('Set-Cookie', 'user_id=; Path=/')

    def initialize(self, *a, **kw):
        webapp2.RequestHandler.initialize(self, *a, **kw)
        uid = self.read_secure_cookie('user_id')
        self.user = uid and User.by_id(int(uid))

def render_post(response, article):
    response.out.write('<b>' + article.subject + '</b><br>')
    response.out.write(article.article)

class MainPage(Handler):
  def get(self):
    articles = greetings = Article.all().order('-created')
    articles_likes = []

    for a in articles:
        likes = db.GqlQuery("select * from Likes where id_article =:1", a.key().id())
        a.likes = likes
        articles_likes.append(a)

    self.render('index.html', user=self.user, articles=articles_likes)


##### user stuff
def make_salt(length = 5):
    return ''.join(random.choice(letters) for x in xrange(length))

def make_pw_hash(name, pw, salt = None):
    if not salt:
        salt = make_salt()
    h = hashlib.sha256(name + pw + salt).hexdigest()
    return '%s,%s' % (salt, h)

def valid_pw(name, password, h):
    salt = h.split(',')[0]
    return h == make_pw_hash(name, password, salt)

def users_key(group = 'default'):
    return db.Key.from_path('users', group)

def login_required(func):
    """
    A decorator to confirm a user is logged in or redirect as needed.
    """
    def login(self, *args, **kwargs):
        # Redirect to login if user not logged in, else execute func.
        if not self.user:
            self.redirect("/login")
        else:
            func(self, *args, **kwargs)

    return login

class User(db.Model):
    name = db.StringProperty(required = True)
    pw_hash = db.StringProperty(required = True)
    email = db.StringProperty()

    @classmethod
    def by_id(cls, uid):
        return User.get_by_id(uid, parent = users_key())

    @classmethod
    def by_name(cls, name):
        u = User.all().filter('name =', name).get()
        return u

    @classmethod
    def register(cls, name, pw, email = None):
        pw_hash = make_pw_hash(name, pw)
        return User(parent=users_key(),
                    name=name,
                    pw_hash=pw_hash,
                    email=email)

    @classmethod
    def login(cls, name, pw):
        u = cls.by_name(name)
        if u and valid_pw(name, pw, u.pw_hash):
            return u

class Likes(db.Model):
    id_user = db.StringProperty(required=True)
    id_article = db.StringProperty(required=True)
    created = db.DateTimeProperty(auto_now_add=True)

def article_key(name = 'default'):
    return db.Key.from_path('articles', name)

class Article(db.Model):
    subject = db.StringProperty(required=True)
    author = db.StringProperty(required=True)
    article = db.TextProperty(required=True)
    created = db.DateTimeProperty(auto_now_add=True)

    def render(self):
        self._render_text = self.article.replace('\n', '<br>')
        return render_str("article.html", p = self)

class BlogFront(Handler):
    def get(self):
        articles = greetings = Article.all().order('-created')
        self.render('index.html', articles = articles)

class PostPage(Handler):
    def get(self, post_id):
        key = db.Key.from_path('Article', int(post_id), parent=article_key())
        article = db.get(key)

        if not article:
            return self.error(404)

        self.render("article.html", article=article)

class EditArticle(Handler):
    @login_required
    def get(self, post_id):
        key = db.Key.from_path('Article', int(post_id), parent=article_key())
        article = db.get(key)

        if not article and article.author == self.user.name:
            error = "You don't have permission to do this"
            self.render('/404.html', error=error)
            return
        self.render("edit.html", article = article)

    @login_required
    def post(self, post_id):
        subject = self.request.get("subject")
        article = self.request.get("article")
        id_article = self.request.get("id_article")

        key = db.Key.from_path('Article', int(id_article), parent=article_key())
        a = db.get(key)

        if a and subject and article and a.author == self.user.name:
            a.subject = subject
            a.article = article
            a.put()
            success = "article update"
            return self.render("edit.html", author=self.user.name, article=a, success=success)

        else:
            error = "Subject and article has to be filled, please!"
            return self.render("edit.html", article=a, error=error)

class RemoveArticle(Handler):
    @login_required
    def get(self, post_id):
        key = db.Key.from_path('Article', int(post_id), parent=article_key())
        article = db.get(key)

        if not article or article.author != self.user.name:
            error = "You don't have permission to do this"
            return self.render('/404.html', error=error)

        article.delete()
        return self.render('/article-delete.html')

class LikeArticle(Handler):
    @login_required
    def get(self, post_id):
        key = db.Key.from_path('Article', int(post_id), parent=article_key())
        article = db.get(key)

        likes = db.GqlQuery("select * from Likes where id_user =:1 and id_article =:2"
                            ,self.user.name
                            ,post_id)
        if likes or article.author == self.user.name:
            return self.redirect('/')

        else:
            if likes.id_user != self.user.name:
               l = Likes(id_user=self.user.name, id_article=post_id)
               l.put()
               return self.redirect('/')

class DisLikeArticle(Handler):
    @login_required
    def get(self, post_id):
        key = db.Key.from_path('Article', int(post_id), parent=article_key())
        article = db.get(key)

        likes = db.GqlQuery("select * from Likes where id_user =:1 and id_article =:2"
                            ,self.user.name
                            ,post_id)

        if likes or article.author != self.user.name:
            for l in likes:
                if l.id_user == self.user.name:
                   l.delete()

            return self.redirect('/')
        else:
            return self.redirect('/')

class NewArticle(Handler):
    @login_required
    def get(self):
        if self.user:
            self.render("form.html")
        else:
            return self.redirect("/login")

    @login_required
    def post(self):
        subject = self.request.get("subject")
        article = self.request.get("article")

        if subject and article:
            p = Article(parent=article_key()
                        ,subject=subject
                        ,author=self.user.name
                        ,article=article)
            p.put()
            return self.redirect('/article/%s' % str(p.key().id()))
        else:
            error = "Subject and article has to be filled, please!"
            self.render("form.html"
                        ,subject=subject
                        ,author=self.user.name
                        ,article=article
                        ,error=error)


USER_RE = re.compile(r"^[a-zA-Z0-9_-]{3,20}$")
def valid_username(username):
    return username and USER_RE.match(username)

PASS_RE = re.compile(r"^.{3,20}$")
def valid_password(password):
    return password and PASS_RE.match(password)

EMAIL_RE  = re.compile(r'^[\S]+@[\S]+\.[\S]+$')
def valid_email(email):
    return not email or EMAIL_RE.match(email)

class Signup(Handler):
    def get(self):
        return self.render("signup-form.html")

    def post(self):
        have_error = False
        self.username=self.request.get('username')
        self.password=self.request.get('password')
        self.verify=self.request.get('verify')
        self.email=self.request.get('email')

        params = dict(username=self.username, email=self.email)

        if not valid_username(self.username):
            params['error_username'] = "That's not a valid username."
            have_error = True

        if not valid_password(self.password):
            params['error_password'] = "That wasn't a valid password."
            have_error = True
        elif self.password != self.verify:
            params['error_verify'] = "Your passwords didn't match."
            have_error = True

        if not valid_email(self.email):
            params['error_email'] = "That's not a valid email."
            have_error = True

        if have_error:
            return self.render('signup-form.html', **params)
        else:
            self.done()

    def done(self, *a, **kw):
        raise NotImplementedError

class Register(Signup):
    def done(self):
        #make sure the user doesn't already exist
        u = User.by_name(self.username)
        if u:
            msg = 'That user already exists.'
            self.render('signup-form.html', error_username=msg)
        else:
            u = User.register(self.username, self.password, self.email)
            u.put()

            self.login(u)
            return self.redirect('/welcome')

class Welcome(Handler):
    def get(self):
        if self.user:
            self.render('welcome.html', username=self.user.name)
        else:
            return self.redirect('/signup')

class Login(Handler):

    def get(self):
        if not self.user:
            self.render('login-form.html')
        else:
            return self.redirect('/')

    def post(self):
        username = self.request.get('username')
        password = self.request.get('password')

        u = User.login(username, password)
        if u:
            self.login(u)
            return self.redirect('/')
        else:
            msg = 'Invalid'
            self.render('login-form.html', error=msg)

class Logout(Handler):
    def get(self):
        self.logout()
        return  self.redirect('/article')

app = webapp2.WSGIApplication([('/', MainPage),
                               ('/article/?', BlogFront),
                               ('/article/([0-9]+)', PostPage),
                               ('/article/new', NewArticle),
                               ('/signup', Register),
                               ('/login', Login),
                               ('/logout', Logout),
                               ('/welcome', Welcome),
                               ('/article/edit/([0-9]+)', EditArticle),
                               ('/article/remove/([0-9]+)', RemoveArticle),
                               ('/article/like/([0-9]+)', LikeArticle),
                               ('/article/dislike/([0-9]+)', DisLikeArticle)
                               ],
                              debug=True)
