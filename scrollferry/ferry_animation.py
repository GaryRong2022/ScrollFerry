"""Original ferry silhouette sailing on the logo's blue sea."""
import math
from functools import lru_cache
from PIL import Image, ImageDraw, ImageOps


SEA_BLUE = '#0b6afb'


SCENE_HEIGHT = 240


@lru_cache(maxsize=4)
def sea_background(width):
    image = Image.new('RGBA',(width*2,480))
    d = ImageDraw.Draw(image)
    for y in range(480):
        t=min(1,y/326)
        color=tuple(round(a+(b-a)*t) for a,b in zip((11,106,251),(127,204,255)))
        if y>=326:
            t=(y-326)/154
            color=tuple(round(a+(b-a)*t) for a,b in zip((45,168,246),(9,112,234)))
        d.line((0,y,width*2,y),fill=(*color,255))
    return image


@lru_cache(maxsize=4)
def coastal_skyline(width):
    """Layered blue silhouettes inspired by the reference's landmark grouping."""
    image=Image.new('RGBA',(width*2,480))
    d=ImageDraw.Draw(image)
    sx=width/520
    def pts(values): return [(round(x*sx*2),round(y*2)) for x,y in values]
    def poly(values,color): d.polygon(pts(values),fill=color)
    def line(values,color,w=1): d.line(pts(values),fill=color,width=w*2)
    def rect(x,y,w,h,color): poly([(x,y),(x+w,y),(x+w,y+h),(x,y+h)],color)
    # Distant buildings remain lighter than the landmark silhouettes.
    far='#529af0'; near='#226aca'; trees='#1a62ba'
    for x,y,w in [(4,113,13),(25,101,15),(46,123,11),(103,99,16),(123,117,12),
                  (148,109,12),(227,102,15),(250,90,16),(271,113,17),(382,105,20),
                  (459,111,12),(481,94,16),(503,118,17)]:
        rect(x,y,w,151-y,far)
    # Tapered modern tower on the left, with a restrained crown line.
    poly([(61,149),(62,82),(65,59),(71,43),(77,37),(83,46),(88,62),(91,83),(93,149)],near)
    line([(77,39),(80,147)],'#458fea')
    for y in (72,95,119):line([(64,y),(89,y)],'#539bef')
    poly([(413,149),(413,64),(428,59),(437,66),(438,149)],near)
    poly([(449,149),(449,49),(459,45),(465,51),(467,149)],'#327cda')
    # Three rising arms of the Spring City monument and the central globe.
    cx=193
    poly([(cx-15,148),(cx-11,113),(cx-23,104),(cx-23,91),(cx-11,81),(cx-8,52),
          (cx-4,49),(cx-5,83),(cx-16,94),(cx-15,102),(cx-5,111),(cx-6,148)],near)
    poly([(cx+4,148),(cx+4,112),(cx+15,101),(cx+16,94),(cx+6,83),(cx+4,48),
          (cx+8,52),(cx+11,80),(cx+23,91),(cx+23,105),(cx+13,115),(cx+14,148)],near)
    d.ellipse([*pts([(cx-7,90)])[0],*pts([(cx+7,104)])[0]],fill='#5397ea')
    # Traditional tiered eaves echo the illuminated tower in the reference.
    cx=335
    for y,half in [(143,30),(126,27),(109,24),(92,21),(75,17)]:
        rect(cx-half+6,y-12,half*2-12,16,near)
        poly([(cx-half-4,y-3),(cx-half+3,y),(cx-7,y-7),(cx+7,y-7),
              (cx+half-3,y),(cx+half+4,y-3),(cx+half,y+4),(cx-half,y+4)],near)
        line([(cx-half+3,y+4),(cx+half-3,y+4)],'#70b3f5')
    line([(cx,64),(cx,58)],near)
    # A continuous tree-lined embankment separates land from water.
    for x in range(-5,527,11):
        y=149+2*math.sin(x*.16)
        d.ellipse([*pts([(x-8,y-9)])[0],*pts([(x+8,y+6)])[0]],fill=trees)
    shore=[(x,157+2*math.sin(x/77)) for x in range(0,521,3)]
    poly(shore+[(520,164),(0,164)],'#195caa')
    line([(x,y+5) for x,y in shore],'#b8eaff')
    for x in range(14,520,30):line([(x,157),(x,162)],'#91d0fc')
    return image


def drifting_clouds(width, seconds):
    layer=Image.new('RGBA',(width*2,480))
    d=ImageDraw.Draw(layer)
    for start,y,size,speed,alpha in [(70,23,25,2.6,75),(265,31,20,1.7,55),(443,15,30,2.1,65)]:
        x=(start-seconds*speed+size*3)%(width+size*6)-size*3
        # Soft flattened cloud silhouettes move more slowly than the boat.
        for dx,dy,rx,ry in [(-.65,0,.65,.22),(0,-.14,.52,.38),(.55,0,.64,.24)]:
            cx=x+dx*size; cy=y+dy*size
            d.ellipse((round((cx-rx*size)*2),round((cy-ry*size)*2),
                       round((cx+rx*size)*2),round((cy+ry*size)*2)),fill=(235,248,255,alpha))
    return layer


def travel_position(seconds, width):
    """A 40-second round trip, slowing gently at both visible endpoints."""
    left, right = 66, max(66,width-66)
    phase = (seconds % 40)/40*2*math.pi
    x = left+(right-left)*(1-math.cos(phase))/2
    return x, 1 if seconds % 40 < 20 else -1


def prepare_ferry_logo(logo):
    """Separate the mark from its blue tile once, before animation starts."""
    mark = logo.convert('RGBA').resize((288,288),Image.Resampling.LANCZOS)
    deck = Image.new('RGBA',mark.size)
    # The diagonal strip between cabin and hull was blue in the app icon;
    # it is an opaque blue deck, not a window through the entire vessel.
    ImageDraw.Draw(deck).polygon([(46,151),(237,128),(237,146),(46,170)],fill='#146dda')
    pixels = []
    data = mark.get_flattened_data() if hasattr(mark, 'get_flattened_data') else mark.getdata()
    for index, (r,g,b,a) in enumerate(data):
        # Preserve the white hull, black face and gold funnel. The original
        # cyan wave and bow bubbles belong to the tile, not the moving boat.
        distance = max(r, abs(g-106), abs(b-251))
        coverage = max(0,min(1,(distance-25)/45))
        if index // mark.width >= 190 and b > r:
            coverage *= max(0, min(1, 1-(g-r)/35))
        pixels.append((r,g,b,round(a*coverage)))
    mark.putdata(pixels)
    return Image.alpha_composite(deck,mark)


def water_height(x, phase):
    return 210 + 2.5*math.sin(x/43 + phase*1.2)


def boat_pose(x, phase):
    # Both heave and pitch follow the very same surface drawn in front of
    # the hull. The lower six pixels sit under water, hiding the old wave cut.
    y = water_height(x, phase)-25
    slope = 2.5/43*math.cos(x/43+phase*1.2)
    tilt = max(-2.5,min(2.5,-math.degrees(math.atan(slope))))
    return y, tilt


def ferry_frame(seconds, arrived=False, width=520, logo=None):
    image = Image.alpha_composite(sea_background(width),drifting_clouds(width,seconds))
    image = Image.alpha_composite(image,coastal_skyline(width))
    phase = seconds
    x, direction = travel_position(seconds,width)
    y, tilt = boat_pose(x,phase)
    if logo is not None:
        mark = logo.resize((224,224),Image.Resampling.LANCZOS)
        if direction < 0:
            mark = ImageOps.mirror(mark)
        mark = mark.rotate(tilt,Image.Resampling.BICUBIC,expand=True)
        image.alpha_composite(mark,(round(x*2-mark.width/2),round(y*2-mark.height/2)))

    # Draw the water AFTER the boat: the hull enters the water instead of
    # hovering over an unrelated line. This is one continuous water surface.
    surface = [(p*2,2*water_height(p,phase)) for p in range(-2,width+3,2)]
    water = sea_background(width)
    water_mask = Image.new('L',image.size)
    ImageDraw.Draw(water_mask).polygon(surface+[(width*2+4,480),(-4,480)],fill=255)
    image = Image.composite(water,image,water_mask)
    layer = Image.new('RGBA',image.size)
    waves = ImageDraw.Draw(layer)
    waves.line(surface,fill=(154,214,245,125),width=3)
    for row in range(1,3):
        points=[(p*2,2*(water_height(p+row*22,phase)+row*14)) for p in range(-2,width+3,3)]
        waves.line(points,fill=(132,201,236,100-row*12),width=2)
    # A short bow ripple and a fading wake begin at the hull's contact points.
    for side, length in ((1,14),(-1,29)):
        facing=side*direction
        start=x+facing*38
        points=[((start+facing*p)*2,2*(water_height(start+facing*p,phase)+2+p*.06)) for p in range(length)]
        waves.line(points,fill=(195,235,255,165 if side==1 else 105),width=3)
    for i in range(3):
        age=(phase*.5+i/3)%1
        cx=x-direction*(43+age*48)
        cy=water_height(cx,phase)+4+age*4
        waves.line([(cx*2,cy*2),((cx+direction*10*(1-age))*2,cy*2)],fill=(166,224,250,int(120*(1-age))),width=2)
    image = Image.alpha_composite(image,layer)
    if arrived:
        d=ImageDraw.Draw(image)
        cx=round(x*2+104);cy=round((y-24)*2)
        d.ellipse((cx-15,cy-15,cx+15,cy+15),fill='white')
        d.line([(cx-7,cy),(cx-2,cy+5),(cx+8,cy-6)],fill='#0877db',width=3)
    return image
