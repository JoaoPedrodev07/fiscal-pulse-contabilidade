from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import User


class TokenObtainPairPTSerializer(TokenObtainPairSerializer):
    """SimpleJWT com mensagens de erro em português."""

    default_error_messages = {
        'no_active_account': 'Credenciais incorretas. Verifique o usuário e a senha.',
    }


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'password']
        extra_kwargs = {'password': {'write_only': True}}

    def create(self, validated_data):
        password = validated_data.pop('password')
        return User.objects.create_user(**validated_data, password=password)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'is_active', 'is_staff', 'date_joined', 'last_login']
        read_only_fields = ['id', 'date_joined', 'last_login', 'is_staff']
