# -*- coding: utf-8 -*-
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Q, F, Sum
from django.db import connections
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

from haystack.query import SearchQuerySet

from .models import Vote, Legislator_Vote
from search.models import Keyword
from standpoint.models import Standpoint, User_Standpoint
from search.views import keyword_list, keyword_been_searched, keyword_normalize
from .tasks import update_vote_index
from commontag.views import paginate


def votes(request):
    qs = Q(content=request.GET['keyword']) if request.GET.get('keyword') else Q()
    qs = qs & Q(conflict=True) if request.GET.get('conscience') else qs
    qs = qs & Q(tags_num__gt=0) if request.GET.get('has_tag') else qs
    qs = qs & Q(tags__in=[request.GET['tag']]) if request.GET.get('tag') else qs
    votes = SearchQuerySet().filter(qs).models(Vote).order_by('-date', 'vote_seq')
    votes = paginate(request, votes)
    keywords = [x.content for x in SearchQuerySet().filter(category__exact=2).models(Keyword).order_by('-hits')]
    standpoints = Standpoint.objects.values('title').annotate(pro_sum=Sum('pro')).order_by('-pro_sum').distinct()
    get_params = '&'.join(['%s=%s' % (x, request.GET[x]) for x in ['keyword', 'conscience', 'has_tag'] if request.GET.get(x)])
    return render(request, 'vote/votes.html', {'votes': votes, 'conscience': request.GET.get('conscience'), 'keyword': request.GET.get('keyword', ''), 'keyword_obj': keywords, 'hot_keyword': keywords[:5], 'hot_standpoints': standpoints[:5], 'get_params': get_params})

def vote(request, vote_id):
    vote = get_object_or_404(Vote.objects.select_related('sitting'), pk=vote_id)
    if request.GET:
        if not request.user.is_authenticated():
            return redirect('%s?next=%s' % (settings.LOGIN_URL, request.get_full_path()))
        if request.GET.get('keyword'):
            Standpoint.objects.get_or_create(title=request.GET['keyword'].strip(), vote_id=vote_id)
            update_vote_index.delay(vote_id)
        elif request.GET.get('standpoint_id'):
            if request.GET.get('against'):
                user_standpoint = User_Standpoint.objects.filter(standpoint_id=request.GET['standpoint_id'], user=request.user)
                if user_standpoint:
                    user_standpoint.delete()
                    Standpoint.objects.filter(pk=request.GET['standpoint_id']).update(pro=F('pro') - 1)
            else:
                obj, created = User_Standpoint.objects.get_or_create(standpoint_id=request.GET['standpoint_id'], user=request.user)
                if created:
                    Standpoint.objects.filter(pk=request.GET['standpoint_id']).update(pro=F('pro') + 1)
            update_vote_index.delay(vote_id)
    standpoints = list(Standpoint.objects.filter(pro__gt=0).values_list('title', flat=True).distinct())
    standpoints_of_vote = Standpoint.objects.filter(vote_id=vote_id)\
                                            .order_by('-pro')
    if request.user.is_authenticated():
        standpoints_of_vote = standpoints_of_vote.extra(select={
            'have_voted': "SELECT true FROM standpoint_user_standpoint su WHERE su.standpoint_id = standpoint_standpoint.id AND su.user_id = %s" % request.user.id,
        },)
    standpoints_of_vote = list(standpoints_of_vote)
    return render(request, 'vote/vote.html', {'vote': vote, 'keyword_obj': standpoints, 'standpoints_of_vote': standpoints_of_vote[:3], 'standpoints_of_vote_hide': standpoints_of_vote[3:]})
